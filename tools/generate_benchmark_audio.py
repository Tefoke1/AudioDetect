"""Generate minute-long synthetic MP3 fixtures after generate_test_audio.ps1."""
import av,numpy as np,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from audio_io import decode_audio
assets=root/'android/app/src/androidTest/assets'
for lang,rate,layout in [('ru',16000,'mono'),('en',44100,'stereo')]:
 speech=decode_audio(assets/f'demo-{lang}.wav')
 audio=np.tile(np.concatenate([np.zeros(16000,dtype=np.float32),speech,np.zeros(16000,dtype=np.float32)]),5)
 output=av.open(str(assets/f'bench-{lang}.mp3'),'w')
 stream=output.add_stream('libmp3lame',rate=rate);stream.layout=layout;stream.bit_rate=64000
 resampler=av.AudioResampler(format='fltp',layout=layout,rate=rate)
 for index in range(0,len(audio),16000):
  frame=av.AudioFrame.from_ndarray(audio[index:index+16000][None,:],format='fltp',layout='mono');frame.sample_rate=16000
  for converted in resampler.resample(frame):
   for packet in stream.encode(converted):output.mux(packet)
 for converted in resampler.resample(None):
  for packet in stream.encode(converted):output.mux(packet)
 for packet in stream.encode(None):output.mux(packet)
 output.close()
 print(lang,round(len(audio)/16000,2),'seconds generated')
