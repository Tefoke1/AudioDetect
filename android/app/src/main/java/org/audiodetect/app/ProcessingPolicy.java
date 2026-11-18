package org.audiodetect.app;

/** Pure, testable resource policy. Accuracy settings are identical in both modes. */
final class ProcessingPolicy {
    static int workers(int cores,long availableMemory,boolean lowMemory,boolean savingPower,
                       int thermalStatus,boolean economical,int files) {
        if (files<2 || economical || savingPower || lowMemory || cores<4
                || availableMemory<1200L*1024*1024 || thermalStatus>=3) return 1;
        return 2;
    }
    static long remainingSeconds(double done,double total,double elapsedSeconds) {
        if(done<=0 || total<=done || elapsedSeconds<3) return -1;
        return Math.max(1,Math.round((total-done)*elapsedSeconds/done));
    }
}
