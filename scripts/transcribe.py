"""转写（带字级时间）。苹果芯片的 Mac 用 mlx-whisper（快），Windows 和 Intel Mac 用 faster-whisper（有 N 卡自动用 CUDA）。
模型 whisper-large-v3-turbo，约 1.5 GB，第一次用时下载；连不上 huggingface.co 时自动改用 hf-mirror.com。

usage: python transcribe.py <口播视频或音频> [--terms "专有名词1, 专有名词2"]
writes: voice16k.wav, transcript.json, words.txt（每段一行：字@秒 ...）

--terms：稿子里的专有名词（产品名、人名）。Whisper 常听错这些，给了会好很多。

在别的脚本里：
  import transcribe as TR
  r = TR.transcribe('voice16k.wav', prompt='...')            # {'text', 'segments': [{start, end, text, words: [...]}]}
  r = TR.transcribe(np_float32_16k, words=False)              # 一小段 numpy 音频
"""
import os, sys, json, platform, subprocess, shutil
import tools

_ENGINE = None
_MODEL = None


def engine():
    """'mlx' 或 'faster'"""
    global _ENGINE
    if _ENGINE is None:
        forced = os.environ.get('BAJ_WHISPER')
        if forced in ('mlx', 'faster'):
            _ENGINE = forced
        elif platform.system() == 'Darwin' and platform.machine() == 'arm64':
            try:
                import mlx_whisper  # noqa: F401
                _ENGINE = 'mlx'
            except Exception:
                _ENGINE = 'faster'
        else:
            _ENGINE = 'faster'
    return _ENGINE


def _hf_reachable():
    curl = shutil.which('curl') or shutil.which('curl.exe')
    if not curl:
        return True
    r = subprocess.run([curl, '-sI', '--max-time', '6', 'https://huggingface.co'], capture_output=True)
    return r.returncode == 0


def _setup_mirror():
    if os.environ.get('HF_ENDPOINT'):
        return
    cache = os.path.join(os.path.expanduser('~'), '.cache', 'huggingface', 'hub')
    have = os.path.isdir(cache) and any('whisper-large-v3-turbo' in d for d in os.listdir(cache))
    if not have and not _hf_reachable():
        os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
        print('连不上 huggingface.co，改用镜像 hf-mirror.com 下载模型', flush=True)


def _faster_model():
    global _MODEL
    if _MODEL is None:
        _setup_mirror()
        from faster_whisper import WhisperModel
        dev, ct = 'cpu', 'int8'
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                dev, ct = 'cuda', 'float16'
        except Exception:
            pass
        name = os.environ.get('BAJ_WHISPER_MODEL', 'large-v3-turbo')
        print(f'加载转写模型 faster-whisper {name}（{dev}）…', flush=True)
        _MODEL = WhisperModel(name, device=dev, compute_type=ct)
    return _MODEL


def transcribe(audio, prompt=None, words=True, prev_text=True):
    """audio = 16 kHz 单声道 wav 路径，或 float32 numpy 数组（16 kHz）"""
    if engine() == 'mlx':
        _setup_mirror()
        import mlx_whisper
        return mlx_whisper.transcribe(audio, path_or_hf_repo=os.environ.get('BAJ_WHISPER_MODEL',
                                      'mlx-community/whisper-large-v3-turbo'), language='zh',
                                      word_timestamps=words, initial_prompt=prompt,
                                      condition_on_previous_text=prev_text)
    m = _faster_model()
    segs, _ = m.transcribe(audio, language='zh', word_timestamps=words, initial_prompt=prompt,
                           condition_on_previous_text=prev_text, vad_filter=False, beam_size=5)
    out = []
    for s in segs:
        out.append(dict(start=s.start, end=s.end, text=s.text,
                        words=[dict(word=w.word, start=w.start, end=w.end, probability=w.probability)
                               for w in (s.words or [])]))
    return dict(text=''.join(s['text'] for s in out), segments=out)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('media')
    ap.add_argument('--terms', default='')
    a = ap.parse_args()
    ff = tools.FFMPEG
    subprocess.run([ff, '-v', 'error', '-y', '-i', a.media, '-vn', '-ac', '1', '-ar', '16000', 'voice16k.wav'], check=True)
    print(f'转写引擎：{engine()}', flush=True)
    r = transcribe('voice16k.wav', prompt=(a.terms + '。') if a.terms else None)
    json.dump(r, open('transcript.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    with open('words.txt', 'w', encoding='utf-8') as f:
        for s in r['segments']:
            f.write(f"[{s['start']:.2f}-{s['end']:.2f}] " +
                    ' '.join(f"{w['word'].strip()}@{w['start']:.2f}" for w in s.get('words', [])) + '\n')
    for s in r['segments']:
        print(f"{s['start']:7.2f} {s['end']:7.2f} {s['text']}")


if __name__ == '__main__':
    main()
