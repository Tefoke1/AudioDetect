package org.audiodetect.app;
import org.junit.Test;
import static org.junit.Assert.*;
public class ProcessingPolicyTest {
    long enough=4L*1024*1024*1024;
    @Test public void powerfulPhoneUsesTwo(){assertEquals(2,ProcessingPolicy.workers(8,enough,false,false,0,false,500));}
    @Test public void resourceLimitsUseOne(){
        assertEquals(1,ProcessingPolicy.workers(8,enough,false,false,3,false,500));
        assertEquals(1,ProcessingPolicy.workers(8,enough,false,true,0,false,500));
        assertEquals(1,ProcessingPolicy.workers(8,enough,true,false,0,false,500));
        assertEquals(1,ProcessingPolicy.workers(8,400L*1024*1024,false,false,0,false,500));
    }
    @Test public void explicitEconomyAndSingleFile(){
        assertEquals(1,ProcessingPolicy.workers(8,enough,false,false,0,true,500));
        assertEquals(1,ProcessingPolicy.workers(8,enough,false,false,0,false,1));
    }
    @Test public void etaNeedsEvidence(){
        assertEquals(-1,ProcessingPolicy.remainingSeconds(0,100,10));
        assertEquals(-1,ProcessingPolicy.remainingSeconds(50,100,1));
        assertEquals(10,ProcessingPolicy.remainingSeconds(50,100,10));
        assertEquals(-1,ProcessingPolicy.remainingSeconds(100,100,10));
    }
}
