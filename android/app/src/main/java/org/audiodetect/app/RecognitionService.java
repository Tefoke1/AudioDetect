package org.audiodetect.app;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.media.*;
import android.net.Uri;
import android.os.*;
import org.json.*;
import org.vosk.*;
import java.io.*;
import java.nio.*;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;

/** Owned process makes Stop independent of a native inference call. No network permission. */
public final class RecognitionService extends Service {
    static final String EVENT="org.audiodetect.app.PROGRESS";
    volatile boolean stopping=false,started=false;Thread worker;String language="ru";PowerManager.WakeLock wake;
    String t(String ru,String en){return language.equals("ru")?ru:en;}
    public IBinder onBind(Intent intent){return null;}
    public int onStartCommand(Intent intent,int flags,int id){
        if(intent!=null && "STOP".equals(intent.getAction())) {stopping=true;signal(t("Остановлено. Готовые результаты сохранены.","Stopped. Completed results are saved."),true);stopForeground(true);stopSelf();android.os.Process.killProcess(android.os.Process.myPid());return START_NOT_STICKY;}
        if(started)return START_NOT_STICKY;started=true;
        language=intent==null?"ru":intent.getStringExtra("uiLanguage");if(language==null)language="ru";
        NotificationManager manager=getSystemService(NotificationManager.class);manager.createNotificationChannel(new NotificationChannel("processing","AudioDetect",NotificationManager.IMPORTANCE_LOW));
        Intent stop=new Intent(this,RecognitionService.class).setAction("STOP");PendingIntent cancel=PendingIntent.getService(this,2,stop,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        Notification notification=new Notification.Builder(this,"processing").setSmallIcon(R.drawable.ic_audio).setContentTitle("AudioDetect").setContentText(t("Распознавание на устройстве","Recognition on this device")).setOngoing(true).addAction(new Notification.Action.Builder(null,t("Стоп","Stop"),cancel).build()).setContentIntent(PendingIntent.getActivity(this,1,new Intent(this,MainActivity.class),PendingIntent.FLAG_IMMUTABLE)).build();
        if(Build.VERSION.SDK_INT>=29)startForeground(1,notification,Build.VERSION.SDK_INT>=35?ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROCESSING:ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);else startForeground(1,notification);
        wake=((PowerManager)getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"AudioDetect:recognition");wake.acquire(6*60*60*1000L);
        getSharedPreferences("state",0).edit().putInt("workerPid",android.os.Process.myPid()).putBoolean("running",true).commit();
        worker=new Thread(this::process,"local-recognition");worker.start();return START_NOT_STICKY;
    }
    void signal(String message,boolean done){sendBroadcast(new Intent(EVENT).setPackage(getPackageName()).putExtra("message",message).putExtra("done",done));if(done)getSharedPreferences("state",0).edit().putBoolean("running",false).commit();}
    File model(String speech)throws Exception {
        String directory=speech.equals("en")?"vosk-model-small-en-us-0.15":"vosk-model-small-ru-0.22";
        File root=new File(getFilesDir(),"models"),destination=new File(root,directory),marker=new File(destination,".complete");if(marker.isFile())return destination;
        signal(t("Подготовка языковой модели…","Preparing the language model…"),false);root.mkdirs();
        try(ZipInputStream zip=new ZipInputStream(getAssets().open("vosk-"+speech+".zip"))) {ZipEntry entry;byte[] bytes=new byte[65536];while((entry=zip.getNextEntry())!=null){if(stopping)throw new InterruptedException();File file=new File(root,entry.getName());if(!file.getCanonicalPath().startsWith(root.getCanonicalPath()+File.separator))throw new IOException("Invalid model archive path");if(entry.isDirectory())file.mkdirs();else {file.getParentFile().mkdirs();try(OutputStream out=new FileOutputStream(file)){int n;while((n=zip.read(bytes))>0)out.write(bytes,0,n);}}}}
        marker.createNewFile();return destination;
    }
    void process(){int ok=0,errors=0;try(Library db=new Library(this)) {
        JSONObject job=new JSONObject(new String(Files.readAllBytes(new File(getFilesDir(),"job.json").toPath()),java.nio.charset.StandardCharsets.UTF_8));String speech=job.getString("language");JSONArray ids=job.getJSONArray("uris");Map<String,Library.Entry> lookup=new HashMap<>();for(Library.Entry e:db.entries())lookup.put(e.uri,e);
        try(Model model=new Model(model(speech).getPath())) {
            for(int i=0;i<ids.length()&&!stopping;i++){String uri=ids.getString(i);Library.Entry e=lookup.get(uri);if(e==null)continue;signal((i+1)+" / "+ids.length()+" · "+e.name,false);
                try {
                    long[] before=fingerprint(Uri.parse(uri),e.size,e.modified);
                    boolean unchanged=before[0]==e.size && before[1]==e.modified;
                    if(unchanged && e.language.equals(speech)&&!e.text.isEmpty()&&e.error.isEmpty()){ok++;continue;}
                    db.add(uri,e.name,before[0],before[1]);
                    JSONArray result=decode(Uri.parse(uri),model);
                    long[] after=fingerprint(Uri.parse(uri),before[0],before[1]);
                    if(!Arrays.equals(before,after))throw new IOException(t("Файл изменился во время обработки","File changed during processing"));
                    db.save(uri,speech,result,"");ok++;
                } catch(Exception ex){db.save(uri,speech,new JSONArray(),ex.getClass().getSimpleName()+": "+ex.getMessage());errors++;}
            }
        }
        signal(t("Готово. Обработано: ","Complete. Processed: ")+ok+t(". Ошибок: ",". Errors: ")+errors,true);
    } catch(Exception e){signal(t("Обработка не завершена: ","Processing did not finish: ")+e.getMessage(),true);} finally {if(wake!=null&&wake.isHeld())wake.release();stopForeground(true);stopSelf();}}
    long[] fingerprint(Uri uri,long size,long modified)throws Exception {
        if("file".equals(uri.getScheme())){File file=new File(uri.getPath());if(!file.isFile())throw new FileNotFoundException("Source file unavailable");return new long[]{file.length(),file.lastModified()};}
        try(android.database.Cursor cursor=getContentResolver().query(uri,null,null,null,null)) {
            if(cursor==null||!cursor.moveToFirst())throw new FileNotFoundException("Source file unavailable");
            int index=cursor.getColumnIndex(android.provider.OpenableColumns.SIZE);if(index>=0&&!cursor.isNull(index))size=cursor.getLong(index);
            index=cursor.getColumnIndex(android.provider.DocumentsContract.Document.COLUMN_LAST_MODIFIED);if(index>=0&&!cursor.isNull(index))modified=cursor.getLong(index);
        }
        return new long[]{size,modified};
    }
    JSONArray decode(Uri uri,Model model)throws Exception {
        MediaExtractor extractor=new MediaExtractor();MediaCodec codec=null;Recognizer recognizer=null;JSONArray segments=new JSONArray();
        try {extractor.setDataSource(this,uri,null);MediaFormat input=null;
            for(int i=0;i<extractor.getTrackCount();i++){MediaFormat f=extractor.getTrackFormat(i);if(f.getString(MediaFormat.KEY_MIME).startsWith("audio/")){input=f;extractor.selectTrack(i);break;}}
            if(input==null)throw new IOException("No supported audio track");
            int rate=input.getInteger(MediaFormat.KEY_SAMPLE_RATE),channels=input.getInteger(MediaFormat.KEY_CHANNEL_COUNT),encoding=AudioFormat.ENCODING_PCM_16BIT;
            recognizer=new Recognizer(model,rate);recognizer.setWords(true);codec=MediaCodec.createDecoderByType(input.getString(MediaFormat.KEY_MIME));codec.configure(input,null,null,0);codec.start();boolean sent=false,done=false;MediaCodec.BufferInfo info=new MediaCodec.BufferInfo();long lastOutput=SystemClock.elapsedRealtime();
            while(!done&&!stopping){
                if(!sent){int index=codec.dequeueInputBuffer(10000);if(index>=0){ByteBuffer buffer=codec.getInputBuffer(index);int length=extractor.readSampleData(buffer,0);if(length<0){codec.queueInputBuffer(index,0,0,0,MediaCodec.BUFFER_FLAG_END_OF_STREAM);sent=true;}else{codec.queueInputBuffer(index,0,length,extractor.getSampleTime(),0);extractor.advance();}}}
                int index=codec.dequeueOutputBuffer(info,10000);
                if(index==MediaCodec.INFO_OUTPUT_FORMAT_CHANGED){MediaFormat f=codec.getOutputFormat();channels=f.getInteger(MediaFormat.KEY_CHANNEL_COUNT);if(f.containsKey(MediaFormat.KEY_PCM_ENCODING))encoding=f.getInteger(MediaFormat.KEY_PCM_ENCODING);if(f.getInteger(MediaFormat.KEY_SAMPLE_RATE)!=rate)throw new IOException("Decoder changed sample rate");}
                else if(index>=0){lastOutput=SystemClock.elapsedRealtime();ByteBuffer pcm=codec.getOutputBuffer(index).order(ByteOrder.LITTLE_ENDIAN);pcm.position(info.offset);pcm.limit(info.offset+info.size);int width=encoding==AudioFormat.ENCODING_PCM_FLOAT?4:2;short[] mono=new short[info.size/width/channels];for(int n=0;n<mono.length;n++){double sum=0;for(int c=0;c<channels;c++)sum+=width==4?Math.max(-1,Math.min(1,pcm.getFloat()))*32767:pcm.getShort();mono[n]=(short)(sum/channels);}if(mono.length>0&&recognizer.acceptWaveForm(mono,mono.length))append(segments,recognizer.getResult());done=(info.flags&MediaCodec.BUFFER_FLAG_END_OF_STREAM)!=0;codec.releaseOutputBuffer(index,false);}
                if(SystemClock.elapsedRealtime()-lastOutput>60000)throw new IOException("Audio decoder timed out");
            }
            if(stopping)throw new InterruptedException();append(segments,recognizer.getFinalResult());return segments;
        }finally{if(recognizer!=null)recognizer.close();if(codec!=null){try{codec.stop();}catch(Exception ignored){}codec.release();}extractor.release();}
    }
    static void append(JSONArray output,String raw)throws JSONException {
        JSONObject result=new JSONObject(raw);JSONArray words=result.optJSONArray("result");if(words==null)return;StringBuilder text=new StringBuilder();double start=0,end=0;
        for(int i=0;i<words.length();i++){JSONObject word=words.getJSONObject(i);double next=word.getDouble("start");if(text.length()>0&&(next-end>.8||next-start>10)){output.put(new JSONObject().put("start",start).put("end",end).put("text",text.toString().trim()));text.setLength(0);}if(text.length()==0)start=next;text.append(word.getString("word")).append(' ');end=word.getDouble("end");}
        if(text.length()>0)output.put(new JSONObject().put("start",start).put("end",end).put("text",text.toString().trim()));
    }
    public void onDestroy(){stopping=true;if(wake!=null&&wake.isHeld())wake.release();super.onDestroy();}
}
