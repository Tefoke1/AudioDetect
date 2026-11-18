package org.audiodetect.app;

import android.content.Context;
import android.media.*;
import android.net.Uri;
import android.os.SystemClock;
import org.json.JSONArray;
import org.vosk.Model;
import org.vosk.Recognizer;
import java.io.IOException;
import java.nio.*;
import java.util.function.BooleanSupplier;

/** Bounded PCM batches; drain MediaCodec without one blocking wait per input packet. */
final class AudioDecoder {
    interface Progress { void update(double seconds, double duration); }
    static final class Result {
        final JSONArray segments = new JSONArray();
        double seconds, duration;
        long recognitionMs, wallMs;
        int batches;
    }
    static Result decode(Context context, Uri uri, Model model, BooleanSupplier cancelled,
                         Progress progress) throws Exception {
        long began = SystemClock.elapsedRealtime();
        Result result = new Result();
        MediaExtractor extractor = new MediaExtractor();
        MediaCodec codec = null;
        Recognizer recognizer = null;
        try {
            extractor.setDataSource(context, uri, null);
            MediaFormat input = null;
            for (int i=0; i<extractor.getTrackCount(); i++) {
                MediaFormat format = extractor.getTrackFormat(i);
                if (format.getString(MediaFormat.KEY_MIME).startsWith("audio/")) {
                    input=format; extractor.selectTrack(i); break;
                }
            }
            if (input==null) throw new IOException("No supported audio track");
            int rate=input.getInteger(MediaFormat.KEY_SAMPLE_RATE);
            int channels=input.getInteger(MediaFormat.KEY_CHANNEL_COUNT);
            if (rate<8000 || rate>192000 || channels<1 || channels>32)
                throw new IOException("Unsupported audio format");
            result.duration=input.containsKey(MediaFormat.KEY_DURATION)
                    ?input.getLong(MediaFormat.KEY_DURATION)/1e6:0;
            int encoding=AudioFormat.ENCODING_PCM_16BIT;
            // A quarter second amortizes JNI/copy cost without changing sample rate or decoder beam.
            short[] batch=new short[Math.max(1,rate/4)];
            int used=0;
            long samples=0, lastProgress=0, lastOutput=SystemClock.elapsedRealtime();
            recognizer=new Recognizer(model,rate);
            recognizer.setWords(true);
            codec=MediaCodec.createDecoderByType(input.getString(MediaFormat.KEY_MIME));
            codec.configure(input,null,null,0); codec.start();
            MediaCodec.BufferInfo info=new MediaCodec.BufferInfo();
            boolean inputEnded=false,outputEnded=false;
            while (!outputEnded) {
                if (cancelled.getAsBoolean()) throw new InterruptedException();
                boolean moved=false;
                // Fill available slots before draining output. Never wait for an occupied input slot.
                for (int n=0;n<16 && !inputEnded;n++) {
                    int index=codec.dequeueInputBuffer(0);
                    if (index<0) break;
                    ByteBuffer buffer=codec.getInputBuffer(index);
                    int length=extractor.readSampleData(buffer,0);
                    if (length<0) {
                        codec.queueInputBuffer(index,0,0,0,MediaCodec.BUFFER_FLAG_END_OF_STREAM);
                        inputEnded=true;
                    } else {
                        codec.queueInputBuffer(index,0,length,extractor.getSampleTime(),0);
                        extractor.advance();
                    }
                    moved=true;
                }
                // Sleep only when neither side can make progress; do not busy-spin.
                int index=codec.dequeueOutputBuffer(info,moved?0:2000);
                if (index==MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    MediaFormat output=codec.getOutputFormat();
                    if (output.getInteger(MediaFormat.KEY_SAMPLE_RATE)!=rate)
                        throw new IOException("Decoder changed sample rate");
                    channels=output.getInteger(MediaFormat.KEY_CHANNEL_COUNT);
                    if(channels<1||channels>32)throw new IOException("Unsupported channel count");
                    encoding=output.containsKey(MediaFormat.KEY_PCM_ENCODING)
                            ?output.getInteger(MediaFormat.KEY_PCM_ENCODING):AudioFormat.ENCODING_PCM_16BIT;
                    if (encoding!=AudioFormat.ENCODING_PCM_16BIT && encoding!=AudioFormat.ENCODING_PCM_FLOAT)
                        throw new IOException("Unsupported PCM encoding");
                } else if (index>=0) {
                    lastOutput=SystemClock.elapsedRealtime();
                    ByteBuffer pcm=codec.getOutputBuffer(index).order(ByteOrder.LITTLE_ENDIAN);
                    pcm.position(info.offset); pcm.limit(info.offset+info.size);
                    int width=encoding==AudioFormat.ENCODING_PCM_FLOAT?4:2;
                    int frames=info.size/width/channels;
                    for (int n=0;n<frames;n++) {
                        double sum=0;
                        for (int c=0;c<channels;c++)
                            sum+=width==4?Math.max(-1,Math.min(1,pcm.getFloat()))*32767:pcm.getShort();
                        batch[used++]=(short)(sum/channels);
                        samples++;
                        if (used==batch.length) {
                            if (cancelled.getAsBoolean()) throw new InterruptedException();
                            accept(recognizer,batch,used,result); used=0;
                        }
                    }
                    outputEnded=(info.flags&MediaCodec.BUFFER_FLAG_END_OF_STREAM)!=0;
                    codec.releaseOutputBuffer(index,false);
                    result.seconds=samples/(double)rate;
                    long now=SystemClock.elapsedRealtime();
                    if (now-lastProgress>=400) {
                        progress.update(result.seconds,result.duration); lastProgress=now;
                    }
                }
                if (SystemClock.elapsedRealtime()-lastOutput>60000)
                    throw new IOException("Audio decoder timed out");
            }
            if (cancelled.getAsBoolean()) throw new InterruptedException();
            if (used>0) accept(recognizer,batch,used,result);
            long finalStart=SystemClock.elapsedRealtime();
            RecognitionService.append(result.segments,recognizer.getFinalResult());
            result.recognitionMs+=SystemClock.elapsedRealtime()-finalStart;
            result.wallMs=SystemClock.elapsedRealtime()-began;
            progress.update(result.seconds,result.duration);
            return result;
        } finally {
            if (recognizer!=null) recognizer.close();
            if (codec!=null) {
                try {codec.stop();} catch (Exception ignored) {}
                codec.release();
            }
            extractor.release();
        }
    }
    private static void accept(Recognizer recognizer,short[] data,int count,Result result)throws Exception {
        long began=SystemClock.elapsedRealtime();
        if(recognizer.acceptWaveForm(data,count)) RecognitionService.append(result.segments,recognizer.getResult());
        result.recognitionMs+=SystemClock.elapsedRealtime()-began;
        result.batches++;
    }
}
