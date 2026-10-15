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

def _fit_caption(draw, text, width, height, scale):
    """Fit Korean text to a legible card without clipping."""
    text = text.strip()
    for pt in [int(v * scale) for v in (88, 82, 76, 70, 64, 58, 52, 46)]:
        ft = font(max(20, pt))
        lines = wrap_korean(draw, text, ft, width)
        bbox = draw.textbbox((0, 0), '가나다', font=ft)
        step = max(24, bbox[3]-bbox[1] + int(24*scale))
        if len(lines)*step <= height:
            return ft, lines, step
    # Exceptionally long scripts are shortened for visual readability only;
    # full script still goes to narration.
    preview = text[:78].rstrip() + ('…' if len(text)>78 else '')
    ft=font(max(20,int(46*scale)))
    lines=wrap_korean(draw, preview, ft, width)
    bbox=draw.textbbox((0,0),'가나다',font=ft)
    return ft, lines, max(24,bbox[3]-bbox[1]+int(20*scale))


def create_frame(text, index, photo=None, theme='블루', size=(1080,1920), style='생활정보 + 감각적인 영상'):
    """Create mobile-first editorial information cards using PIL only."""
    w,h=size
    s=w/1080.0
    X=lambda n: int(n*s)
    schemes={
        '블루': ((10,24,42),(16,58,78),(65,207,192)),
        '크림': ((44,32,32),(104,64,61),(255,196,116)),
        '그린': ((9,37,35),(20,75,61),(157,226,145)),
    }
    top,bottom,accent=schemes.get(theme,schemes['블루'])
    gradient=Image.new('RGB',(1,h))
    px=gradient.load()
    for y in range(h):
        t=y/max(1,h-1)
        px[0,y]=tuple(int(top[k]*(1-t)+bottom[k]*t) for k in range(3))
    im=gradient.resize((w,h))
    photo_used=photo is not None
    if photo_used:
        shot=ImageOps.fit(photo.convert('RGB'),(w,h),method=Image.Resampling.LANCZOS,centering=(.5,.47))
        shot=shot.filter(ImageFilter.GaussianBlur(max(0.5,1.0*s)))
        im=Image.blend(im,shot,0.77)
        veil=Image.new('RGBA',(w,h),(0,0,0,0)); v=ImageDraw.Draw(veil)
        for j in range(16):
            y0=int(h*j/16)
            opacity=int(80 + 116*j/15)
            v.rectangle((0,y0,w,int(h*(j+1)/16)+2),fill=(5,11,20,opacity))
        im=Image.alpha_composite(im.convert('RGBA'),veil).convert('RGB')
    else:
        # Abstract art makes a useful fallback when licensed photos are absent.
        decor=Image.new('RGBA',(w,h),(0,0,0,0)); d0=ImageDraw.Draw(decor)
        d0.ellipse((X(600),X(70),X(1400),X(870)),fill=(*accent,35),outline=(*accent,105),width=X(5))
        d0.ellipse((X(-400),X(580),X(560),X(1540)),outline=(255,255,255,32),width=X(5))
        d0.rounded_rectangle((X(670),X(380),X(1070),X(830)),radius=X(75),outline=(*accent,105),width=X(4))
        im=Image.alpha_composite(im.convert('RGBA'),decor).convert('RGB')
    lay=Image.new('RGBA',(w,h),(0,0,0,0)); d=ImageDraw.Draw(lay)
    m=X(64)
    # Brand and section header.
    d.rounded_rectangle((m,X(116),X(430),X(188)),radius=X(30),fill=(*accent,245))
    d.text((X(91),X(130)),'MIA  /  JAKARTA',font=font(X(36)),fill=(8,23,32,255))
    tag=['한눈에 보기','첫 번째 팁','두 번째 팁','세 번째 팁','저장해 두세요'][min(index,4)]
    d.text((m,X(268)),f'{index+1:02d}   {tag}',font=font(X(49)),fill=(255,255,255,250),stroke_width=X(1),stroke_fill=(0,0,0,120))
    d.rounded_rectangle((m,X(374),w-m,X(385)),radius=X(5),fill=(*accent,245))
    # Subtitles are the star: a large semi-opaque card with ample padding.
    card_top=X(700 if style.startswith('생활정보') else 840)
    card_bottom=X(1530)
    d.rounded_rectangle((m,card_top,w-m,card_bottom),radius=X(45),fill=(8,17,30,211),outline=(255,255,255,55),width=max(1,X(2)))
    d.rounded_rectangle((X(104),card_top+X(48),X(238),card_top+X(61)),radius=X(6),fill=(*accent,255))
    d.text((X(105),card_top+X(94)),'JAKARTA LIFE TIPS',font=font(X(35)),fill=(*accent,255))
    max_text_height=card_bottom-(card_top+X(220))-X(62)
    ft,lines,step=_fit_caption(d,text,w-X(210),max_text_height,s)
    yy=card_top+X(215)
    for line in lines:
        # Heavy shadow and outlined white improve readability on photographs.
        d.text((X(107)+X(3), yy+X(4)),line,font=ft,fill=(0,0,0,200),stroke_width=max(1,X(3)),stroke_fill=(0,0,0,160))
        d.text((X(107),yy),line,font=ft,fill=(255,255,255,255))
        yy+=step
    # Lower-safe-zone info strip; do not place content at screen bottom.
    d.text((m,X(1622)),'생활에 바로 쓰는 자카르타 정보',font=font(X(37)),fill=(255,255,255,230))
    bar_y=X(1713)
    d.rounded_rectangle((m,bar_y,w-m,bar_y+X(13)),radius=X(7),fill=(255,255,255,65))
    d.rounded_rectangle((m,bar_y,m+int((w-2*m)*(index+1)/5),bar_y+X(13)),radius=X(7),fill=(*accent,255))
    d.text((m,X(1750)),'SAVE  •  SHARE  •  FOLLOW',font=font(X(31)),fill=(255,255,255,200))
    return Image.alpha_composite(im.convert('RGBA'),lay).convert('RGB')

def ffmpeg_run(args):
    p=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y',*args],capture_output=True,text=True)
    if p.returncode: raise RuntimeError(p.stderr[-2000:])

def render(scenes, photos, theme, voice, music_bytes=None, progress=None, quality='빠른 제작 (540p)', style='생활정보 + 감각적인 영상'):
    # Render each scene separately; quality affects speed but not subtitle composition.
    quick=quality.startswith('빠른')
    output_size=(540,960) if quick else (1080,1920)
    fps=15 if quick else 24
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
            frame=create_frame(script,i,photo,theme,output_size,style)
            image=wd/f'frame_{i}.jpg';frame.save(image,quality=82 if quick else 90)
            seg=wd/f'seg_{i}.mp4'
            ffmpeg_run(['-loop','1','-framerate',str(fps),'-i',str(image),'-i',str(audio),'-t',str(duration),'-c:v','libx264','-preset','ultrafast' if quick else 'veryfast','-tune','stillimage','-threads','2','-pix_fmt','yuv420p','-r',str(fps),'-af','apad','-c:a','aac','-b:a','96k' if quick else '128k','-ar','44100','-ac','2','-movflags','+faststart',str(seg)])
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

st.title('🎬 Mia Reels Studio 2.1')
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
    elif mode.startswith('OpenAI') and not api_key:st.error('Streamlit Secrets에서 OPENAI_API_KEY 설정을 확인하세요.')
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
style=st.selectbox('자막과 배경 디자인',['생활정보 + 감각적인 영상','시네마틱 카드형'],help='장면별로 큰 한글 자막과 정보 카드 디자인을 사용합니다.')
photos_upload=st.file_uploader('선택: 사진 최대 5장 (없으면 기본 배경 사용)',type=['png','jpg','jpeg'],accept_multiple_files=True)
music_upload=st.file_uploader('선택: 저작권 사용 권한이 있는 MP3 배경음악',type=['mp3'])
photos=[]
for f in (photos_upload or [])[:5]:
    try:photos.append(Image.open(io.BytesIO(f.read())).convert('RGB'))
    except Exception:st.warning(f'{f.name} 사진을 읽을 수 없습니다.')
if photos:
    st.caption('사진은 업로드한 순서대로 장면에 배치됩니다. 부족한 장면에는 기본 배경이 적용됩니다.')
st.caption('사진이 없으면 감각적인 추상 배경을 사용합니다. 실제 사진 자동 검색이나 동영상 클립 삽입은 아직 제공하지 않습니다.')
with st.expander('🎨 장면 디자인 미리보기',expanded=False):
    if scenes[0]:
        preview=create_frame(scenes[0],0,photos[0] if photos else None,theme,(540,960),style)
        st.image(preview,caption='첫 번째 장면 미리보기 (음성 및 영상 제작 전)',width=270)
st.subheader('⑤ MP4 만들기')
st.caption('음성 생성은 인터넷이 필요합니다. 긴 영상은 시간이 더 걸리며 무료 서버의 자원 제한을 받을 수 있습니다.')
quality=st.selectbox('영상 화질 / 제작 속도', ['빠른 제작 (540p)', '고화질 (1080p)'], help='먼저 빠른 제작으로 확인한 뒤 최종 게시용은 고화질을 선택하세요.')
st.caption('빠른 제작은 540×960 / 15fps, 고화질은 1080×1920 / 24fps로 출력합니다.')
if st.button('🎥 한국어 음성 + 자막 + MP4 자동 생성',type='primary',use_container_width=True):
    if not all(scenes):st.error('5개 장면의 문구를 모두 입력해 주세요.')
    else:
        try:
            p=st.progress(0,text='준비 중...')
            data=render(scenes,photos,theme,voice,music_upload.getvalue() if music_upload else None,p,quality,style)
            st.session_state['video_bytes']=data
            st.success('릴스 영상 완성!')
        except Exception as e:
            st.error(f'영상 생성 실패: {e}')
            st.info('긴 대본이라면 빠른 제작 (540p)으로 재시도하세요. 실패 시 Manage app의 로그를 확인하세요.')
if st.session_state.get('video_bytes'):
    st.video(st.session_state.video_bytes)
    st.download_button('⬇️ 완성된 릴스 MP4 다운로드',data=st.session_state.video_bytes,file_name='mia_reels.mp4',mime='video/mp4',use_container_width=True)
st.divider()
st.caption('주의: 기본 대본은 사실 확인을 대신하지 않습니다. AI 생성 문구, 사진 및 음악의 사용 권한을 게시 전 확인하세요. 자동 인스타그램 게시 기능은 포함되어 있지 않습니다.')
