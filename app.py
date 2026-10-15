import os, io, re, json, math, tempfile, subprocess, textwrap
from pathlib import Path
import streamlit as st
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
from gtts import gTTS
import imageio_ffmpeg

st.set_page_config(page_title='Mia Reels Studio', page_icon='🎬', layout='wide')
FONT_CANDIDATES = [
    os.environ.get('MIA_FONT',''),
    '/usr/share/fonts/truetype/nanum/NanumSquareB.ttf',
    '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
    'C:/Windows/Fonts/malgunbd.ttf',
    'C:/Windows/Fonts/malgun.ttf',
    '/System/Library/Fonts/AppleSDGothicNeo.ttc',
]

def font(sz):
    for p in FONT_CANDIDATES:
        if p and Path(p).exists():
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()

def wrap_korean(draw, txt, ft, max_width):
    lines=[]
    for para in txt.split('\n'):
        line=''
        for ch in para:
            candidate=line+ch
            if line and draw.textbbox((0,0), candidate, font=ft)[2] > max_width:
                lines.append(line.strip()); line=ch
            else: line=candidate
        if line.strip(): lines.append(line.strip())
    return lines or ['']

def default_scenes(topic):
    topic=topic.strip().rstrip('.!?')
    return [
      f'{topic}\n궁금하셨나요?',
      f'오늘은 {topic}에 대해\n핵심만 살펴볼게요.',
      '첫째, 이용 조건과\n적용 지역을 확인하세요.',
      '둘째, 실제 비용과\n최신 후기를 비교하세요.',
      '셋째, 공식 안내를 확인하고\n나에게 맞게 선택하세요.\n유용했다면 저장해 주세요!'
    ]

def ai_scenes(topic, api_key, model):
    from openai import OpenAI
    client=OpenAI(api_key=api_key, timeout=35)
    r=client.chat.completions.create(
      model=model,
      messages=[
        {'role':'system','content':'너는 한국어 인스타그램 릴스 대본 작가다. 사용자가 제공하지 않은 구체적 사실, 가격, 업체 정보, 실사용 경험을 지어내지 않는다. 5개 장면, 장면당 한국어 1~2문장, 최대 55자. 첫 장면은 후킹, 마지막 장면은 저장 CTA. 오직 JSON {"scenes":["...",...]} 형식으로 답하라.'},
        {'role':'user','content':f'주제: {topic}'}
      ], temperature=0.6,
      response_format={'type':'json_object'}
    )
    scenes=json.loads(r.choices[0].message.content)['scenes']
    if len(scenes)!=5 or not all(isinstance(x,str) and x.strip() for x in scenes):
        raise ValueError('AI 대본이 5개 장면 형식이 아닙니다.')
    return scenes

def create_frame(text, index, photo=None, theme='블루', size=(1080,1920)):
    w,h=size
    colors={'블루':((11,30,65),(24,111,174)), '크림':((35,39,49),(155,117,87)), '그린':((11,55,54),(25,115,90))}
    a,b=colors[theme]
    im=Image.new('RGB',(w,h)); px=im.load()
    for y in range(h):
        t=y/(h-1)
        c=tuple(int(a[k]*(1-t)+b[k]*t) for k in range(3))
        ImageDraw.Draw(im).line([(0,y),(w,y)],fill=c)
    if photo is not None:
        photo=ImageOps.fit(photo.convert('RGB'),(w,h),method=Image.Resampling.LANCZOS,centering=(.5,.5))
        photo=photo.filter(ImageFilter.GaussianBlur(1))
        im=Image.blend(im,photo,.58)
        overlay=Image.new('RGBA',(w,h),(0,0,0,0))
        od=ImageDraw.Draw(overlay)
        od.rectangle((0,0,w,h),fill=(0,0,0,75))
        im=Image.alpha_composite(im.convert('RGBA'),overlay).convert('RGB')
    d=ImageDraw.Draw(im)
    d.rounded_rectangle((70,105,530,180),radius=26,fill=(255,255,255))
    d.text((100,119),'MIA REELS STUDIO',font=font(37),fill=(18,50,72))
    d.text((78,240),f'{index+1:02d} / 05',font=font(48),fill=(255,255,255))
    main=font(79 if len(text)<55 else 66)
    lines=wrap_korean(d,text,main,w-150)
    spacing=31
    bbox=d.textbbox((0,0),'가나다',font=main)
    line_h=(bbox[3]-bbox[1])+spacing
    y=max(580,(h-line_h*len(lines))//2)
    for line in lines:
        bb=d.textbbox((0,0),line,font=main)
        x=(w-(bb[2]-bb[0]))//2
        d.text((x+3,y+4),line,font=main,fill=(0,0,0),stroke_width=4,stroke_fill=(0,0,0))
        d.text((x,y),line,font=main,fill=(255,255,255),stroke_width=1,stroke_fill=(255,255,255))
        y+=line_h
    d.rounded_rectangle((78,h-240,w-78,h-226),radius=7,fill=(255,255,255,75))
    d.rounded_rectangle((78,h-240,78+(w-156)*(index+1)//5,h-226),radius=7,fill=(255,255,255))
    d.text((78,h-190),'자카르타 생활정보  |  저장하고 다시 보기',font=font(38),fill='white')
    return im

def ffmpeg_run(args):
    p=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y',*args],capture_output=True,text=True)
    if p.returncode: raise RuntimeError(p.stderr[-2000:])

def render(scenes, photos, theme, voice, music_bytes=None, progress=None):
    # Narration is generated for each scene separately, ensuring scene/caption synchronization.
    with tempfile.TemporaryDirectory() as td:
        wd=Path(td); segments=[]
        for i,script in enumerate(scenes):
            if progress: progress.progress((i+.1)/6, text=f'{i+1}/5 장면: 음성 생성 중')
            audio=wd/f'voice_{i}.mp3'
            gTTS(text=script.replace('\n',' '),lang='ko',slow=False).save(str(audio))
            # Determine exact narration length via ffprobe-like FFmpeg probe using input info is avoided.
            # MP3 duration via mutagen is reliable for gTTS output.
            from mutagen.mp3 import MP3
            duration=max(3.0, MP3(str(audio)).info.length+0.65)
            photo=photos[i] if i<len(photos) else None
            frame=create_frame(script,i,photo,theme)
            image=wd/f'frame_{i}.jpg';frame.save(image,quality=90)
            seg=wd/f'seg_{i}.mp4'
            ffmpeg_run(['-loop','1','-framerate','25','-i',str(image),'-i',str(audio),'-t',str(duration),'-c:v','libx264','-preset','veryfast','-tune','stillimage','-pix_fmt','yuv420p','-r','25','-af','apad','-c:a','aac','-b:a','128k','-ar','44100','-ac','2','-movflags','+faststart',str(seg)])
            segments.append(seg)
            if progress:progress.progress((i+1)/6,text=f'{i+1}/5 장면 완성')
        manifest=wd/'list.txt'
        manifest.write_text(''.join(f"file '{p.as_posix()}'\n" for p in segments),encoding='utf8')
        combined=wd/'joined.mp4'
        ffmpeg_run(['-f','concat','-safe','0','-i',str(manifest),'-c','copy',str(combined)])
        out=wd/'final.mp4'
        if music_bytes:
            music=wd/'music.mp3';music.write_bytes(music_bytes)
            ffmpeg_run(['-i',str(combined),'-stream_loop','-1','-i',str(music),'-filter_complex','[0:a]volume=1.0[a0];[1:a]volume=0.10[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[a]','-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-b:a','128k','-movflags','+faststart',str(out)])
        else:out=combined
        if progress:progress.progress(1.0,text='MP4 완성!')
        return out.read_bytes()

st.title('🎬 Mia Reels Studio')
st.caption('주제 한 줄 → 한국어 대본 → 음성 → 자막 포함 9:16 릴스 MP4')
st.info('처음에는 5개 장면의 사진형 릴스를 만듭니다. 실제 촬영 영상이나 생성형 AI 동영상은 사용하지 않으며, AI API는 선택 사항입니다.')
topic=st.text_input('① 영상 주제',value='자카르타에서 유용한 생활 앱 3가지')
mode=st.radio('② 대본 작성', ['무료 기본 대본','OpenAI로 대본 작성 (API 요금 발생)'],horizontal=True)
api_key='';model='gpt-4o-mini'
if mode.startswith('OpenAI'):
        api_key=st.secrets.get('OPENAI_API_KEY', '')
    model=st.text_input('모델 이름',value='gpt-4o-mini')
if 'scenes' not in st.session_state:st.session_state.scenes=default_scenes(topic)
if st.button('✨ 5개 장면 대본 만들기',type='primary'):
    if not topic.strip():st.error('주제를 입력하세요.')
    elif mode.startswith('OpenAI') and not api_key:st.error('API 키를 입력하세요.')
    else:
        try:
            with st.spinner('대본 작성 중...'):
                st.session_state.scenes=ai_scenes(topic,api_key,model) if mode.startswith('OpenAI') else default_scenes(topic)
            st.success('대본을 만들었습니다. 사실관계를 확인하고 문구를 수정하세요.')
        except Exception as e:st.error(f'대본 생성 실패: {e}')
st.subheader('③ 대본 확인 및 수정')
scenes=[]
for i in range(5):
    val=st.text_area(f'{i+1}번 장면',value=st.session_state.scenes[i],key=f'scene_{i}_{hash(tuple(st.session_state.scenes))}',height=100)
    scenes.append(val.strip())
st.subheader('④ 디자인 및 음성')
c1,c2=st.columns(2)
with c1: theme=st.selectbox('색상 테마',['블루','크림','그린'])
with c2:voice=st.selectbox('음성',['한국어 기본 음성 (gTTS)'])
photos_upload=st.file_uploader('선택: 사진 최대 5장 (없으면 기본 배경 사용)',type=['png','jpg','jpeg'],accept_multiple_files=True)
music_upload=st.file_uploader('선택: 저작권 사용 권한이 있는 MP3 배경음악',type=['mp3'])
photos=[]
for f in (photos_upload or [])[:5]:
    try:photos.append(Image.open(io.BytesIO(f.read())).convert('RGB'))
    except Exception:st.warning(f'{f.name} 사진을 읽을 수 없습니다.')
if photos:
    st.caption('사진은 업로드한 순서대로 장면에 배치됩니다. 부족한 장면에는 기본 배경이 적용됩니다.')
st.subheader('⑤ MP4 만들기')
st.caption('음성 생성은 인터넷이 필요합니다. 영상 합성은 기기 성능에 따라 수 분 걸릴 수 있습니다.')
if st.button('🎥 한국어 음성 + 자막 + MP4 자동 생성',type='primary',use_container_width=True):
    if not all(scenes):st.error('5개 장면의 문구를 모두 입력해 주세요.')
    else:
        try:
            p=st.progress(0,text='준비 중...')
            data=render(scenes,photos,theme,voice,music_upload.getvalue() if music_upload else None,p)
            st.session_state['video_bytes']=data
            st.success('릴스 영상 완성!')
        except Exception as e:st.error(f'영상 생성 실패: {e}. 인터넷 연결 및 설치 안내를 확인해 주세요.')
if st.session_state.get('video_bytes'):
    st.video(st.session_state.video_bytes)
    st.download_button('⬇️ 완성된 릴스 MP4 다운로드',data=st.session_state.video_bytes,file_name='mia_reels.mp4',mime='video/mp4',use_container_width=True)
st.divider()
st.caption('주의: 기본 대본은 사실 확인을 대신하지 않습니다. AI 생성 문구, 사진 및 음악의 사용 권한을 게시 전 확인하세요. 자동 인스타그램 게시 기능은 포함되어 있지 않습니다.')
