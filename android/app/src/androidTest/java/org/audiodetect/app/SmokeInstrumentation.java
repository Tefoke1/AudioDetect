package org.audiodetect.app;
import android.app.*;
import android.content.*;
import android.os.*;
import android.net.Uri;
import android.view.accessibility.*;
import android.graphics.Bitmap;
import java.io.*;
import java.nio.file.*;
import org.json.*;

/** Run only with generated, fictional demo-en.wav and demo-ru.wav test assets. */
public class SmokeInstrumentation extends Instrumentation {
 String language="en";boolean benchmark=false;
 public void onCreate(Bundle arguments){super.onCreate(arguments);language=arguments.getString("language","en");benchmark=arguments.getString("benchmark","false").equals("true");start();}
 private void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
 public void onStart(){Bundle result=new Bundle();MainActivity activity=null;
  try {
   if(benchmark){result.putString("stream",DecoderBenchmark.run(this).toString(2)+"\n");finish(Activity.RESULT_OK,result);return;}
   Context target=getTargetContext();
   for(String lang:new String[]{"en","ru"})try(InputStream in=getContext().getAssets().open("demo-"+lang+".wav")){Files.copy(in,new File(target.getFilesDir(),"demo-"+lang+".wav").toPath(),StandardCopyOption.REPLACE_EXISTING);}
   Intent intent=new Intent(target,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);activity=(MainActivity)startActivitySync(intent);
   MainActivity ui=activity;waitForIdleSync();
   runOnMainSync(()->{check(ui.languageDialog!=null,"Language chooser missing");ui.languageDialog.getListView().performItemClick(null,language.equals("en")?1:0,1);});waitForIdleSync();
   File speech=new File(target.getFilesDir(),"demo-"+language+".wav");String uri=Uri.fromFile(speech).toString();
   try(Library db=new Library(target)){db.getWritableDatabase().delete("recordings",null,null);db.add(uri,"demo-"+language+".wav",speech.length(),speech.lastModified());}
   runOnMainSync(()->{ui.refreshFiles();ui.speech.setSelection(language.equals("en")?1:0);ui.mode.setSelection(1);ui.query.setText(language.equals("en")?"contract payment":"договор оплата");ui.show(true);ui.start();});
   boolean complete=false;String transcript="";
   for(int i=0;i<120;i++){Thread.sleep(500);try(Library db=new Library(target)){for(Library.Entry entry:db.entries())if(entry.uri.equals(uri)){check(entry.error.isEmpty(),"Recognition error: "+entry.error);if(!entry.text.isEmpty()){transcript=entry.words();complete=true;}}}if(complete)break;}
   check(complete,"Recognition timed out");check(Search.matches(transcript,language.equals("en")?"contract payment":"договор оплата",1,true),"Expected keywords absent: "+transcript);check(!Search.matches(transcript,"volcano submarine",1,true),"Unexpected match");
   Thread.sleep(1000);runOnMainSync(ui::search);
   boolean[] found={false};
   for(int i=0;i<30;i++){Thread.sleep(100);runOnMainSync(()->found[0]=!ui.matches.isEmpty());if(found[0])break;}
   check(found[0],"No UI matches");
   for(int stage=0;stage<3;stage++){final int page=stage;runOnMainSync(()->ui.showStage(page));waitForIdleSync();Thread.sleep(300);
    try(OutputStream image=new FileOutputStream(new File(target.getFilesDir(),"screen-"+language+"-"+stage+".png"))){getUiAutomation().takeScreenshot().compress(Bitmap.CompressFormat.PNG,100,image);}
   }

   try(OutputStream image=new FileOutputStream(new File(target.getFilesDir(),"smoke-ui.png"))){getUiAutomation().takeScreenshot().compress(Bitmap.CompressFormat.PNG,100,image);}
   // Repeating the query must reuse committed text without loading an ASR model.
   runOnMainSync(()->{ui.readProgress();check(!ui.running,"First job still running");ui.start();
    try{ui.applyProgress(new org.json.JSONObject().put("jobId","stale-job").put("done",true));}
    catch(Exception e){throw new RuntimeException(e);}check(ui.running,"Stale progress interrupted a new job");});
   boolean cacheDone=false;
   for(int i=0;i<60;i++){Thread.sleep(100);runOnMainSync(ui::readProgress);boolean[] busy={false};runOnMainSync(()->busy[0]=ui.running);if(!busy[0]){cacheDone=true;break;}}
   check(cacheDone,"Cache-only job timed out");
   org.json.JSONObject cached=new org.json.JSONObject(new String(Files.readAllBytes(new File(target.getFilesDir(),"progress.json").toPath()),java.nio.charset.StandardCharsets.UTF_8));
   check(cached.getInt("cached")==1&&cached.getInt("workers")==0,"Repeated query re-ran recognition");
   // Combined filters and bulk checking affect only the visible subset.
   try(Library db=new Library(target)){db.add("test:alpha","alpha.mp3",1048576,1704067200000L);db.add("test:beta","beta.mp3",2097152,1704153600000L);}
   runOnMainSync(()->{ui.nameFilter.setText("alpha");ui.sizeMin.setText("0.5");ui.sizeMax.setText("1.5");ui.dateFrom.setText("2024-01-01");ui.dateTo.setText("2024-01-02");ui.refreshFiles();
    check(ui.visible.size()==1,"Combined filters failed");ui.bulk(false);
    check(ui.library.entries().stream().anyMatch(e->e.name.equals("beta.mp3")&&e.selected),"Bulk check changed hidden entries");
    ui.nameFilter.setText("");ui.sizeMin.setText("");ui.sizeMax.setText("");ui.dateFrom.setText("");ui.dateTo.setText("");
    ui.library.getWritableDatabase().delete("recordings","uri IN (?,?)",new String[]{"test:alpha","test:beta"});ui.refreshFiles();});
   // Changing speech model forces fresh work; Stop must retain the committed English transcript.
   runOnMainSync(()->{ui.speech.setSelection(language.equals("en")?0:1);ui.start();});Thread.sleep(150);long stopped=SystemClock.elapsedRealtime();runOnMainSync(ui::stop);
   for(int i=0;i<40;i++){Thread.sleep(25);boolean active=false;for(ActivityManager.RunningServiceInfo item:((ActivityManager)target.getSystemService(Context.ACTIVITY_SERVICE)).getRunningServices(100))if(item.service.getClassName().equals(RecognitionService.class.getName()))active=true;if(!active)break;}
   ActivityManager manager=(ActivityManager)target.getSystemService(Context.ACTIVITY_SERVICE);boolean alive=false;for(ActivityManager.RunningServiceInfo s:manager.getRunningServices(100))if(s.service.getClassName().equals(RecognitionService.class.getName()))alive=true;check(!alive,"Recognition process did not stop");
   try(Library db=new Library(target)){check(!db.entries().get(0).text.isEmpty(),"Completed transcript lost on Stop");}
   result.putString("stream","PASS: offline "+language+" recognition, positive and negative search, UI results, cancellation, saved transcript, cache-only rerun, stale progress isolation and combined bulk filters. Stop check ms="+(SystemClock.elapsedRealtime()-stopped)+"\n");finish(Activity.RESULT_OK,result);
  }catch(Throwable e){result.putString("stream","FAIL: "+e+"\n");finish(Activity.RESULT_CANCELED,result);}
 }
}