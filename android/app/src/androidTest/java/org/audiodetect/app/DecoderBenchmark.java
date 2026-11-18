package org.audiodetect.app;

import android.app.Instrumentation;
import android.content.Context;
import android.net.Uri;
import android.os.*;
import org.json.*;
import org.vosk.Model;
import java.io.*;
import java.nio.file.*;
import java.util.concurrent.*;

/** Reproducible baseline comparison, synthetic audio only, never in the release APK. */
final class DecoderBenchmark {
    static String words(JSONArray parts){
        StringBuilder result=new StringBuilder();
        for(int i=0;i<parts.length();i++)result.append(parts.optJSONObject(i).optString("text")).append(' ');
        return result.toString().trim();
    }
    static JSONObject run(Instrumentation test)throws Exception {
        Context target=test.getTargetContext();
        JSONObject report=new JSONObject().put("device",Build.MODEL).put("abi",Build.SUPPORTED_ABIS[0])
            .put("cores",Runtime.getRuntime().availableProcessors()).put("syntheticOnly",true);
        JSONArray runs=new JSONArray();
        for(String lang:new String[]{"ru","en"}){
            File file=new File(target.getFilesDir(),"bench-"+lang+".mp3");
            try(InputStream in=test.getContext().getAssets().open(file.getName())){
                Files.copy(in,file.toPath(),StandardCopyOption.REPLACE_EXISTING);
            }
            String modelName=lang.equals("ru")?"vosk-model-small-ru-0.22":"vosk-model-small-en-us-0.15";
            long start=SystemClock.elapsedRealtime();
            try(Model model=new Model(new File(target.getFilesDir(),"models/"+modelName).getPath())){
                JSONObject row=new JSONObject().put("language",lang).put("modelLoadMs",SystemClock.elapsedRealtime()-start);
                JSONArray oldTimes=new JSONArray(),newTimes=new JSONArray(),asrTimes=new JSONArray(),pairTimes=new JSONArray();
                Uri uri=Uri.fromFile(file);String oldWords="",newWords="";double duration=0;
                for(int iteration=0;iteration<3;iteration++){
                    long began=SystemClock.elapsedRealtime();
                    JSONArray old=LegacyDecoder.decode(target,uri,model);
                    oldTimes.put(SystemClock.elapsedRealtime()-began);oldWords=words(old);
                    AudioDecoder.Result next=AudioDecoder.decode(target,uri,model,()->false,(a,b)->{});
                    newTimes.put(next.wallMs);asrTimes.put(next.recognitionMs);newWords=words(next.segments);duration=next.seconds;
                    String query=lang.equals("ru")?"договор оплата":"contract payment";
                    if(!Search.matches(oldWords,query,1,true)||!Search.matches(newWords,query,1,true))
                        throw new AssertionError("Benchmark keyword recall changed: "+lang);
                    if(Search.matches(newWords,"volcano submarine",1,true))throw new AssertionError("False match");
                }
                ExecutorService pool=Executors.newFixedThreadPool(2);
                try {
                    for(int iteration=0;iteration<3;iteration++){
                        long began=SystemClock.elapsedRealtime();
                        Future<AudioDecoder.Result> a=pool.submit(()->AudioDecoder.decode(target,uri,model,()->false,(x,y)->{}));
                        Future<AudioDecoder.Result> b=pool.submit(()->AudioDecoder.decode(target,uri,model,()->false,(x,y)->{}));
                        a.get();b.get();pairTimes.put(SystemClock.elapsedRealtime()-began);
                    }
                }finally{pool.shutdown();pool.awaitTermination(10,TimeUnit.SECONDS);}
                row.put("audioSeconds",duration).put("baselineMs",oldTimes).put("optimizedMs",newTimes)
                    .put("recognitionMs",asrTimes).put("optimizedPairMs",pairTimes).put("sameWords",oldWords.equals(newWords));
                runs.put(row);
            }
        }
        report.put("runs",runs);
        Files.write(new File(target.getFilesDir(),"benchmark.json").toPath(),report.toString(2).getBytes(java.nio.charset.StandardCharsets.UTF_8));
        return report;
    }
}
