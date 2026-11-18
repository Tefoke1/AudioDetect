package org.audiodetect.app;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.net.Uri;
import android.os.*;
import org.json.*;
import org.vosk.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.zip.*;

/** Separate process makes Stop immediate even during native inference. */
public final class RecognitionService extends Service {
    static final String EVENT="org.audiodetect.app.PROGRESS";
    volatile boolean stopping,started;
    String language="ru",jobId="";
    PowerManager.WakeLock wake;
    ExecutorService pool;
    final Map<String,FileProgress> active=new ConcurrentHashMap<>();
    final AtomicInteger ok=new AtomicInteger(),errors=new AtomicInteger(),cached=new AtomicInteger();
    int total,workers;
    long began,lastSignal,finishedWeight,totalWeight;
    double finishedAudio;
    String t(String ru,String en){return language.equals("ru")?ru:en;}
    static final class FileProgress {
        String name;long weight;volatile double seconds,duration;
        FileProgress(Library.Entry e){name=e.name;weight=Math.max(e.size,1);}
    }
    public IBinder onBind(Intent intent){return null;}
    public int onStartCommand(Intent intent,int flags,int id) {
        if(intent!=null && "STOP".equals(intent.getAction())) {
            stopping=true;
            signal(t("Остановлено. Готовые результаты сохранены.","Stopped. Completed results are saved."),true);
            stopForeground(true);stopSelf();android.os.Process.killProcess(android.os.Process.myPid());
            return START_NOT_STICKY;
        }
        if(started)return START_NOT_STICKY;
        started=true;began=SystemClock.elapsedRealtime();
        jobId=intent==null?"":intent.getStringExtra("jobId");if(jobId==null)jobId="";
        language=intent==null?"ru":intent.getStringExtra("uiLanguage");if(language==null)language="ru";
        NotificationManager manager=getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel("processing","AudioDetect",NotificationManager.IMPORTANCE_LOW));
        PendingIntent cancel=PendingIntent.getService(this,2,new Intent(this,RecognitionService.class).setAction("STOP"),
                PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        Notification notification=new Notification.Builder(this,"processing").setSmallIcon(R.drawable.ic_audio)
                .setContentTitle("AudioDetect").setContentText(t("Поиск в выбранных записях","Searching selected recordings"))
                .setOngoing(true).addAction(new Notification.Action.Builder(null,t("Остановить","Stop"),cancel).build())
                .setContentIntent(PendingIntent.getActivity(this,1,new Intent(this,MainActivity.class),PendingIntent.FLAG_IMMUTABLE)).build();
        if(Build.VERSION.SDK_INT>=29)startForeground(1,notification,Build.VERSION.SDK_INT>=35
                ?ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROCESSING:ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        else startForeground(1,notification);
        wake=((PowerManager)getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"AudioDetect:recognition");
        wake.acquire(6*60*60*1000L);
        signal(t("Проверяем готовый текст…","Checking saved text…"),false);
        new Thread(this::process,"recognition-coordinator").start();
        return START_NOT_STICKY;
    }
    synchronized void signal(String message,boolean done) {
        try {
            double elapsed=(SystemClock.elapsedRealtime()-began)/1000.0;
            JSONObject state=new JSONObject().put("jobId",jobId).put("message",message).put("done",done)
                    .put("completed",ok.get()+errors.get()).put("total",total).put("cached",cached.get())
                    .put("errors",errors.get()).put("workers",workers).put("elapsed",elapsed);
            double audio=finishedAudio,weight=finishedWeight;
            JSONArray current=new JSONArray();
            for(FileProgress p:active.values()) {
                audio+=p.seconds;
                weight+=p.weight*(p.duration>0?Math.min(.99,p.seconds/p.duration):0);
                current.put(new JSONObject().put("name",p.name).put("seconds",p.seconds).put("duration",p.duration));
            }
            state.put("audioSeconds",audio).put("active",current);
            state.put("fraction",total>0&&ok.get()+errors.get()>=total?1:totalWeight==0?0:Math.min(.99,weight/totalWeight));
            state.put("remaining",done?-1:ProcessingPolicy.remainingSeconds(weight,totalWeight,elapsed));
            File temp=new File(getFilesDir(),"progress.tmp"),destination=new File(getFilesDir(),"progress.json");
            Files.write(temp.toPath(),state.toString().getBytes(StandardCharsets.UTF_8));
            Files.move(temp.toPath(),destination.toPath(),StandardCopyOption.REPLACE_EXISTING);
            sendBroadcast(new Intent(EVENT).setPackage(getPackageName()).putExtra("state",state.toString())
                    .putExtra("message",message).putExtra("done",done));
        } catch(Exception ignored) {}
    }
    synchronized void progress() {
        long now=SystemClock.elapsedRealtime();
        if(now-lastSignal<500)return;lastSignal=now;
        signal(t("Проверяем записи…","Checking recordings…"),false);
    }
    File model(String speech)throws Exception {
        String directory=speech.equals("en")?"vosk-model-small-en-us-0.15":"vosk-model-small-ru-0.22";
        File root=new File(getFilesDir(),"models"),destination=new File(root,directory),marker=new File(destination,".complete");
        if(marker.isFile())return destination;
        signal(t("Подготовка модели при первом запуске…","Preparing the model for first use…"),false);root.mkdirs();
        try(ZipInputStream zip=new ZipInputStream(getAssets().open("vosk-"+speech+".zip"))) {
            ZipEntry entry;byte[] bytes=new byte[65536];
            while((entry=zip.getNextEntry())!=null) {
                if(stopping)throw new InterruptedException();
                File file=new File(root,entry.getName());
                if(!file.getCanonicalPath().startsWith(root.getCanonicalPath()+File.separator))throw new IOException("Invalid model archive path");
                if(entry.isDirectory())file.mkdirs();
                else {
                    file.getParentFile().mkdirs();
                    try(OutputStream out=new FileOutputStream(file)){
                        int n;while((n=zip.read(bytes))>0){if(stopping)throw new InterruptedException();out.write(bytes,0,n);}
                    }
                }
            }
        }
        marker.createNewFile();return destination;
    }
    int workerCount(boolean economical,int files) {
        ActivityManager.MemoryInfo memory=new ActivityManager.MemoryInfo();
        ((ActivityManager)getSystemService(ACTIVITY_SERVICE)).getMemoryInfo(memory);
        PowerManager power=(PowerManager)getSystemService(POWER_SERVICE);
        return ProcessingPolicy.workers(Runtime.getRuntime().availableProcessors(),memory.availMem,memory.lowMemory,
                power.isPowerSaveMode(),Build.VERSION.SDK_INT>=29?power.getCurrentThermalStatus():0,economical,files);
    }
    void process() {
        try(Library db=new Library(this)) {
            JSONObject job=new JSONObject(new String(Files.readAllBytes(new File(getFilesDir(),"job.json").toPath()),StandardCharsets.UTF_8));
            String speech=job.getString("language");JSONArray ids=job.getJSONArray("uris");total=ids.length();
            Map<String,Library.Entry> lookup=new HashMap<>();for(Library.Entry e:db.entries())lookup.put(e.uri,e);
            List<Library.Entry> pending=new ArrayList<>();
            for(int i=0;i<ids.length()&&!stopping;i++) {
                String uri=ids.getString(i);Library.Entry e=lookup.get(uri);
                if(e==null){errors.incrementAndGet();continue;}
                long weight=Math.max(e.size,1);totalWeight+=weight;
                try {
                    long[] before=fingerprint(Uri.parse(uri),e.size,e.modified);
                    boolean unchanged=before[0]==e.size&&before[1]==e.modified;
                    if(unchanged&&e.language.equals(speech)&&!e.text.isEmpty()&&e.error.isEmpty()) {
                        cached.incrementAndGet();ok.incrementAndGet();finishedWeight+=weight;continue;
                    }
                    db.add(uri,e.name,before[0],before[1]);totalWeight+=Math.max(before[0],1)-weight;
                    e.size=before[0];e.modified=before[1];pending.add(e);
                } catch(Exception ex){db.save(uri,speech,new JSONArray(),error(ex));errors.incrementAndGet();finishedWeight+=weight;}
            }
            if(!pending.isEmpty()&&!stopping)runPending(db,pending,speech,job.optBoolean("economical"));
            signal(t("Готово. Проверено: ","Complete. Checked: ")+ok.get()+t(". Из сохранённых: ",". From saved text: ")+
                    cached.get()+t(". Ошибок: ",". Errors: ")+errors.get(),true);
        } catch(Throwable ex) {
            if(!stopping)signal(t("Проверка не завершена: ","Search did not finish: ")+error(ex),true);
        } finally {
            if(pool!=null)pool.shutdownNow();
            if(wake!=null&&wake.isHeld())wake.release();
            stopForeground(true);stopSelf();
        }
    }
    void runPending(Library db,List<Library.Entry> pending,String speech,boolean economical)throws Exception {
        workers=workerCount(economical,pending.size());
        Model shared=new Model(model(speech).getPath());
        pool=Executors.newFixedThreadPool(workers);
        try {
            CompletionService<Void> completion=new ExecutorCompletionService<>(pool);
            Iterator<Library.Entry> iterator=pending.iterator();int inFlight=0;
            while((iterator.hasNext()||inFlight>0)&&!stopping) {
                int allowed=Math.min(workers,workerCount(economical,pending.size()));
                while(iterator.hasNext()&&inFlight<allowed) {
                    Library.Entry entry=iterator.next();
                    completion.submit(()->{recognize(db,shared,speech,entry);return null;});inFlight++;
                }
                Future<Void> result=completion.poll(500,TimeUnit.MILLISECONDS);
                if(result!=null){result.get();inFlight--;}progress();
            }
        } finally {
            pool.shutdown();
            // No queued task may create a recognizer after the shared model has closed.
            while(!pool.awaitTermination(500,TimeUnit.MILLISECONDS)) {
                if(stopping)pool.shutdownNow();
            }
            shared.close();
        }
    }
    void recognize(Library db,Model shared,String speech,Library.Entry e) {
        android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_BACKGROUND);
        FileProgress state=new FileProgress(e);active.put(e.uri,state);
        try {
            AudioDecoder.Result result=AudioDecoder.decode(this,Uri.parse(e.uri),shared,()->stopping,
                    (seconds,duration)->{state.seconds=seconds;state.duration=duration;progress();});
            long[] after=fingerprint(Uri.parse(e.uri),e.size,e.modified);
            if(after[0]!=e.size||after[1]!=e.modified)throw new IOException(t("Файл изменился во время обработки","File changed during processing"));
            if(stopping)return;
            db.save(e.uri,speech,result.segments,"");ok.incrementAndGet();
            synchronized(this){finishedAudio+=result.seconds;}
        } catch(Exception ex) {
            if(!stopping){db.save(e.uri,speech,new JSONArray(),error(ex));errors.incrementAndGet();}
        } finally {
            synchronized(this){finishedWeight+=state.weight;active.remove(e.uri);}progress();
        }
    }
    static String error(Throwable e){String text=e.getMessage();return text==null?e.getClass().getSimpleName():text;}
    long[] fingerprint(Uri uri,long size,long modified)throws Exception {
        if("file".equals(uri.getScheme())) {
            File file=new File(uri.getPath());if(!file.isFile())throw new FileNotFoundException("Source file unavailable");
            return new long[]{file.length(),file.lastModified()};
        }
        try(android.database.Cursor cursor=getContentResolver().query(uri,null,null,null,null)) {
            if(cursor==null||!cursor.moveToFirst())throw new FileNotFoundException("Source file unavailable");
            int index=cursor.getColumnIndex(android.provider.OpenableColumns.SIZE);
            if(index>=0&&!cursor.isNull(index))size=cursor.getLong(index);
            index=cursor.getColumnIndex(android.provider.DocumentsContract.Document.COLUMN_LAST_MODIFIED);
            if(index>=0&&!cursor.isNull(index))modified=cursor.getLong(index);
        }
        return new long[]{size,modified};
    }
    static void append(JSONArray output,String raw)throws JSONException {
        JSONObject result=new JSONObject(raw);JSONArray words=result.optJSONArray("result");if(words==null)return;
        StringBuilder text=new StringBuilder();double start=0,end=0;
        for(int i=0;i<words.length();i++) {
            JSONObject word=words.getJSONObject(i);double next=word.getDouble("start");
            if(text.length()>0&&(next-end>.8||next-start>10)) {
                output.put(new JSONObject().put("start",start).put("end",end).put("text",text.toString().trim()));text.setLength(0);
            }
            if(text.length()==0)start=next;text.append(word.getString("word")).append(' ');end=word.getDouble("end");
        }
        if(text.length()>0)output.put(new JSONObject().put("start",start).put("end",end).put("text",text.toString().trim()));
    }
    @Override public void onTimeout(int startId,int type) {
        stopping=true;signal(t("Android ограничил фоновую работу. Продолжите в приложении.",
                "Android limited background processing. Resume in the app."),true);
        stopForeground(true);stopSelf();android.os.Process.killProcess(android.os.Process.myPid());
    }
    public void onDestroy(){stopping=true;if(wake!=null&&wake.isHeld())wake.release();super.onDestroy();}
}
