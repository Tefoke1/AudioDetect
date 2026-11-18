package org.audiodetect.app;
import android.media.*;
import android.net.Uri;
import android.os.*;
import org.json.*;
import org.vosk.*;
import java.io.*;
import java.nio.*;
/** Previous release decoding loop, test-only baseline. */
final class LegacyDecoder {
    static JSONArray decode(android.content.Context context,Uri uri,Model model)throws Exception {
        MediaExtractor extractor=new MediaExtractor();MediaCodec codec=null;Recognizer recognizer=null;JSONArray segments=new JSONArray();
        try {extractor.setDataSource(context,uri,null);MediaFormat input=null;
            for(int i=0;i<extractor.getTrackCount();i++){MediaFormat f=extractor.getTrackFormat(i);if(f.getString(MediaFormat.KEY_MIME).startsWith("audio/")){input=f;extractor.selectTrack(i);break;}}
            if(input==null)throw new IOException("No supported audio track");
            int rate=input.getInteger(MediaFormat.KEY_SAMPLE_RATE),channels=input.getInteger(MediaFormat.KEY_CHANNEL_COUNT),encoding=AudioFormat.ENCODING_PCM_16BIT;
            recognizer=new Recognizer(model,rate);recognizer.setWords(true);codec=MediaCodec.createDecoderByType(input.getString(MediaFormat.KEY_MIME));codec.configure(input,null,null,0);codec.start();boolean sent=false,done=false;MediaCodec.BufferInfo info=new MediaCodec.BufferInfo();long lastOutput=SystemClock.elapsedRealtime();
            while(!done&&true){
                if(!sent){int index=codec.dequeueInputBuffer(10000);if(index>=0){ByteBuffer buffer=codec.getInputBuffer(index);int length=extractor.readSampleData(buffer,0);if(length<0){codec.queueInputBuffer(index,0,0,0,MediaCodec.BUFFER_FLAG_END_OF_STREAM);sent=true;}else{codec.queueInputBuffer(index,0,length,extractor.getSampleTime(),0);extractor.advance();}}}
                int index=codec.dequeueOutputBuffer(info,10000);
                if(index==MediaCodec.INFO_OUTPUT_FORMAT_CHANGED){MediaFormat f=codec.getOutputFormat();channels=f.getInteger(MediaFormat.KEY_CHANNEL_COUNT);if(f.containsKey(MediaFormat.KEY_PCM_ENCODING))encoding=f.getInteger(MediaFormat.KEY_PCM_ENCODING);if(f.getInteger(MediaFormat.KEY_SAMPLE_RATE)!=rate)throw new IOException("Decoder changed sample rate");}
                else if(index>=0){lastOutput=SystemClock.elapsedRealtime();ByteBuffer pcm=codec.getOutputBuffer(index).order(ByteOrder.LITTLE_ENDIAN);pcm.position(info.offset);pcm.limit(info.offset+info.size);int width=encoding==AudioFormat.ENCODING_PCM_FLOAT?4:2;short[] mono=new short[info.size/width/channels];for(int n=0;n<mono.length;n++){double sum=0;for(int c=0;c<channels;c++)sum+=width==4?Math.max(-1,Math.min(1,pcm.getFloat()))*32767:pcm.getShort();mono[n]=(short)(sum/channels);}if(mono.length>0&&recognizer.acceptWaveForm(mono,mono.length))RecognitionService.append(segments,recognizer.getResult());done=(info.flags&MediaCodec.BUFFER_FLAG_END_OF_STREAM)!=0;codec.releaseOutputBuffer(index,false);}
                if(SystemClock.elapsedRealtime()-lastOutput>60000)throw new IOException("Audio decoder timed out");
            }
            RecognitionService.append(segments,recognizer.getFinalResult());return segments;
        }finally{if(recognizer!=null)recognizer.close();if(codec!=null){try{codec.stop();}catch(Exception ignored){}codec.release();}extractor.release();}
    }
}
