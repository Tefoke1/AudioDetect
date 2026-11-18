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
 String language="en";
 public void onCreate(Bundle arguments){super.onCreate(arguments);language=arguments.getString("language","en");start();}
 private void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
 public void onStart(){Bundle result=new Bundle();MainActivity activity=null;
  try {
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
   Thread.sleep(1000);runOnMainSync(()->{ui.search();check(!ui.matches.isEmpty(),"No UI matches");});
   try(OutputStream image=new FileOutputStream(new File(target.getFilesDir(),"smoke-ui.png"))){getUiAutomation().takeScreenshot().compress(Bitmap.CompressFormat.PNG,100,image);}
   // Changing speech model forces fresh work; Stop must retain the committed English transcript.
   runOnMainSync(()->{ui.speech.setSelection(language.equals("en")?0:1);ui.start();});Thread.sleep(150);long stopped=SystemClock.elapsedRealtime();runOnMainSync(ui::stop);Thread.sleep(800);
   ActivityManager manager=(ActivityManager)target.getSystemService(Context.ACTIVITY_SERVICE);boolean alive=false;for(ActivityManager.RunningServiceInfo s:manager.getRunningServices(100))if(s.service.getClassName().equals(RecognitionService.class.getName()))alive=true;check(!alive,"Recognition process did not stop");
   try(Library db=new Library(target)){check(!db.entries().get(0).text.isEmpty(),"Completed transcript lost on Stop");}
   result.putString("stream","PASS: offline "+language+" recognition, positive and negative search, UI results, cancellation and saved transcript. Stop check ms="+(SystemClock.elapsedRealtime()-stopped)+"\n");finish(Activity.RESULT_OK,result);
  }catch(Throwable e){result.putString("stream","FAIL: "+e+"\n");finish(Activity.RESULT_CANCELED,result);}
 }
}