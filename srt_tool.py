#!/usr/bin/env python3

"""Translate/combine srt files and/or generate them with whisper.
"""
import argparse
import copy
import datetime
import functools
import io
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

import srt

__version__ = '0.1.0'

WHISPER_ARGS = [
    '--compute_type=float32',  # makes it work on CPUs
    '--threads=8',
    '--condition_on_previous_text=False',  # improves quality a bit
    '--initial_prompt=Hello, and welcome to day 3 of our lecture.  Today, we will discuss varous topics.',
    ]


def main():
    """Main program logic: split by sub-command.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--color', default='#87cefa', help='Default %(default)s')
    parser.add_argument('--lang', default='fi', help='Default %(default)s')
    parser.add_argument('--model', default='large-v3', help='Default %(default)s')
    parser.add_argument('--output', type=Path, help='Override output file')

    subparsers = parser.add_subparsers()

    sp_single = subparsers.add_parser('simple', help="Whisper transcribe to *.srt (no language code in filename)")
    sp_single.add_argument('video', nargs='+', type=Path)
    sp_single.set_defaults(simple=True)

    sp_trs = subparsers.add_parser('transcribe', help='transcribe to *.LANG.srt')
    sp_trs.add_argument('video', nargs='+', type=Path)
    sp_trs.set_defaults(whisper_transcribe=True)

    sp_trl = subparsers.add_parser('translate', help='translate to (english) *.ex.srt')
    sp_trl.add_argument('video', nargs='+', type=Path)
    sp_trs.set_defaults(whisper_translate=True)

    sp_combine = subparsers.add_parser('combine', help='combine two srt files, coloring the second one')
    sp_combine.add_argument('srt1', type=Path)
    sp_combine.add_argument('srt2', type=Path)
    sp_combine.add_argument('srtout', type=Path)
    sp_combine.set_defaults(combine=True)

    for name, transfunc in [('argos', translate_argos), ('google', translate_google), ('azure', translate_azure)]:
        sp = subparsers.add_parser(name, help=f'Translate srt with {name}')
        sp.add_argument('srt', type=Path)
        sp.add_argument('srtout', type=Path)
        sp.set_defaults(translate=True, translate_func=transfunc)


    sp_auto = subparsers.add_parser('auto', help="Transcribe, translate, and combine subs, make new .mkv file.  If extension is .orig.mkv, output is .new.mkv, otherwise it is .new.mkv replacing the last portion.")
    sp_auto.add_argument('video', nargs='+', type=Path)
    sp_auto.add_argument('--no-new-mkv', action='store_true')
    sp_auto.add_argument('--re-combine', action='store_true', help="Recombine to .xx.srt, .new.mkv even if they already exist.")
    sp_auto.add_argument('--sid-original', help="Original subtitle id for translation.  If given without --sid-original-lang, this is the subtitle track number.  If given with that option, it is relative to all subtitles of thet language (and can be negative to say 'the last one'")
    sp_auto.add_argument('--sid-original-lang', help="Original subtitle id for translation.  Use ffprobe to see what the options are.")
    sp_auto.add_argument('-w', '--whisper', action='store_true', help="Transcribe with Whisper.")
    sp_auto.add_argument('-W', '--whisper-trans', action='store_true', help="Translate with Whisper.")
    for name, letter, extra in [
        ('argos', 'r', ''),
        ('google', 'g', ', requires manual interaction to do the translation'),
        ('azure', 'z', ''),
        ]:
        sp_auto.add_argument(f'-{letter}', f'--{name}', action='store_true',
                             help=f"{name.title()} translate{extra} (set --sid-original)")
        sp_auto.add_argument(f'-{letter.upper()}', f'--{name}-whisper', action='store_true',
                             help=f"{name.title()} translate of whisper subtitles.")
    sp_auto.set_defaults(auto=True)

    args = parser.parse_args()
    print(args)

    # Simple mode
    if hasattr(args, 'simple'):
        for video in args.video:
            subs = whisper(video, args=args)
            output = args.output or video.with_suffix('.srt')
            output.write_text(srt.compose(subs))
    # Transcribe
    elif hasattr(args, 'whisper_transcribe'):
        for video in args.video:
            subs = whisper(video, args=args)
            output = args.output or video.with_suffix(f'.{args.lang}.srt')
            output.write_text(srt.compose(subs))
    # Whisper-translate
    elif hasattr(args, 'whisper_translate'):
        for video in args.video:
            subs = whisper(video, translate=True, args=args)
            output = args.output or video.with_suffix('.qen.srt')
            output.write_text(srt.compose(subs))
    # Combine
    elif hasattr(args, 'combine'):
        subsnew = combine(read_subs(args.srt1), read_subs(args.srt2), args=args)
        args.srtout.write_text(srt.compose(subsnew))
    # Translate (via any method)
    elif hasattr(args, 'translate'):
        subs = read_subs(args.srt)
        subs = args.translate_func(subs, args=args)
        args.srtout.write_text(srt.compose(subs))

    # Default = auto: trs + trl + combine + make new mkv
    elif hasattr(args, 'auto'):
        for video in args.video:
            whisper_auto(video, args=args)
    else:
        print("No action specified")
        sys.exit(1)


def whisper(video, translate=False, *, args):
    """Run whisper with specifid input/output/arguments, return subs."""
    with tempfile.TemporaryDirectory(prefix='whisper-') as tmpdir:
        cmd = [
            'whisper-ctranslate2',
            'file:'+str(video),
            *WHISPER_ARGS,
            '--output_format=srt',
            '--language='+args.lang,
            '--model='+args.model,
            *(['--task=translate'] if translate else []),
            '--output_dir='+tmpdir,
            ]
        subprocess.run(cmd, check=True)
        print(tuple(Path(tmpdir).iterdir()))
        srtout = Path(tmpdir)/(Path('file:'+str(video)).stem+'.srt')
        return list(srt.parse(open(srtout)))



def recolor(subs, color):
    """Iterate through srt subs, applying a color to all"""
    for s in subs:
        s.content = '\n'.join(f'<font color="{color}">{x}</font>' for x in s.content.split('\n'))
        yield s


def timeshift(subs, shift=0.001):
    """Add a given timestamp to all subs."""
    subs = copy.deepcopy(subs)
    for s in subs:
        s.start += datetime.timedelta(seconds=shift)
        s.end   += datetime.timedelta(seconds=shift)
        yield s



def batched(iter_, n):
    """Return batches from an iterator.  itertools.batched but for older Python."""
    i = 0
    while i < len(iter_):
        yield iter_[i:i+n]
        i += n



def read_subs(filename):
    """Read a file and get subtitles from it, however it may be.

    If .srt: parse the subs.

    If video: get first track.  If it ends in :LANG:N, then return that respective one."""

    video_re = re.compile(r':([a-zA-Z]+):([0-9]+)$')
    filename = Path(filename)
    # .srt files: read directly and parse
    if filename.suffix == '.srt':
        return list(srt.parse(filename.read_text()))
    # Ends in `:LANG:ID` : extract the specified track from it
    if video_re.search(str(filename)):
        m = video_re.search(str(filename))
        lang, track = m.group(1), int(m.group(2))
        filename = Path(str(filename)[:m.start()])
        return subs_from_file(filename, track=track, track_language=lang)
    # Return the first subtitle track
    return subs_from_file(filename, track=0)



def subs_from_file(video, track, track_language=None):
    """Grab srt subtitles from a file.

    `track` is the subtitle track ID (starting from 0 for the first subtitle track).

    `track_language` adjusts the meaning of `track.  If given, only
    consider tracks matching that language.  Select the relevant track
    from those.  0 means first, and -1 means last.
    """
    # Figure out which track we want
    cmd = [
        'ffprobe', 'file:'+str(video), '-loglevel', 'warning',
        '-print_format', 'json', '-show_format', '-show_streams',
        ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, check=True)
    data = json.loads(p.stdout.decode())
    streams = data['streams']

    if isinstance(track, str) and ':' in track:
        track_language, track = track.split(':', 1)
    track = int(track)
    # If a language is specificed, take index only from ones in that language
    if track_language:
        data = [x for x in streams if x['codec_type']=='subtitle' and x['tags']['language'] == track_language]
        try:
            track = data[track]['index']
        except IndexError:
            def filterdict(x):
                new = {k: v for k,v in x.items() if k in {'index', 'codec_type', }}
                new['language'] = x['tags']['language']
                return new
            data = [filterdict(x) for x in streams if x['codec_type']=='subtitle']
            raise RuntimeError(f"Bad subtitle track/track-lang combination {track} and {track_language} in {video}.  Try ffprobe on the file or see here: ({data})")
        track_map = f'0:{track}'
    else:
        track_map = f'0:s:{track}'

    # Get the subtitle
    cmd = [
        'ffmpeg',
        '-i', 'file:'+str(video),
        '-map', track_map, # grab the track we want
        '-f', 'srt',            #output format
        '-loglevel', 'warning',
        '-',                    # output to stdout
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, check=True)
    #print(p.stdout)
    return list(srt.parse(p.stdout.decode()))



def translate_argos(subs, *, args):
    """Translate through the Argos open-source translator"""
    cmd = [
        '/home/rkdarst/sys/argostranslate/argospipe.py',
        args.lang,
        'en',
        ]
    with subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, encoding='utf8') as p:
        (child_stdin, child_stdout) = (p.stdin, p.stdout)
        speaker_re = re.compile(r'((?:\s|^)-)(?=\w)', re.MULTILINE)
        subs = copy.deepcopy(subs)

        # For each subtitle
        for s in subs:
            content = s.content
            print(json.dumps(content))

            # Split it to the different `-` eparated speaker parts
            parts = speaker_re.split(content)
            # insert ensures that `parts` is a sequence of (`-` delimiter,
            # text) pairs, even if the first one is empty
            parts.insert(0, '')
            result = [ ]
            for part in batched(parts, n=2):
                delim, text = part
                text = text.replace('\n', ' ')
                if not text.strip(): continue

                print(repr(text), '--->')
                child_stdin.write(json.dumps(text)+'\n')
                child_stdin.flush()
                new = json.loads(child_stdout.readline())
                print('          --->', repr(new))
                result.append(delim+new)
            s.content = '  '.join(result)
        return subs

def translate_google(subs, *, args):
    """Translate through Google (manual work)"""

    subs = copy.deepcopy(list(subs))
    submap = { i: s.content.replace('\n', ' ') for i,s in enumerate(subs) }
    i = 0

    while i < len(submap):
        #import pdb ; pdb.set_trace()
        next = [ ]
        size = 0
        while size < 4950 and i < len(submap):
            #print(s)
            line = f"{i}→ {submap[i]}"
            next.append(line)
            size += len(line)+1  # +1 for newline
            i += 1
        stdin = '\n'.join(next)
        #print(stdin)
        while True:
            subprocess.run(['xclip', '-in'], input=stdin.encode(), check=True)
            subprocess.run(['xclip', '-in', '-selection', 'clipboard'], input=stdin.encode(), check=True)
            print(f"Copying {len(stdin)} bytes... paste into Google Translate {args.lang}→en")


            while True:
                time.sleep(1)
                print("Waiting for you to copy the output translation...")
                p = subprocess.run(['xclip', '-out', '-selection', 'clipboard'], stdout=subprocess.PIPE, check=True)
                stdout = p.stdout.decode()
                if stdout != stdin:
                    break

            try:
                for line in stdout.split('\n'):
                    newi, newtext = line.split('→', 1)
                    subs[int(newi)].content = newtext.strip()
                break
            except Exception as exc:
                import traceback
                traceback.print_exc()
                print(exc)
                print("failure parsing, try again")
                continue

    return subs



def translate_azure(subs, *, args):
    """Translate through Azure.  Requires API access"""

    key = os.environ['AZURE_KEY']
    import requests
    def auth(r):
        r.headers['Ocp-Apim-Subscription-Key'] = key
        # location required if you're using a multi-service or regional (not global) resource.
        #r.headers['Ocp-Apim-Subscription-Region'] = location
        r.headers['Content-type'] = 'application/json'
        #r.headers['X-ClientTraceId'] = str(uuid.uuid4())
        return r

    subs = copy.deepcopy(list(subs))
    chars = 0
    for i, s in enumerate(subs):
        content = ' '.join(s.content.split('\n'))
        chars += len(content)
        r = requests.post(
            'https://api.cognitive.microsofttranslator.com/translate',
            params={'api-version': '3.0', 'from': args.lang, 'to': ['en']},
            json=[{'text': content}],
            auth=auth
            )
        r.raise_for_status()
        new = r.json()[0]['translations'][0]['text']
        s.content = new
        print(f"Azure: {content!r} → {new!r}")
        #if i > 10:
        #    break
    print(f"Azure: Translated {chars} characters")
    return subs




def whisper_auto(video, *, args):
    """Automatically run translate/transcribe/combine to new file.

    - Whisper transcribe
    - Whisper translate
    - Combine them into one srt file
    - Create a .new.mkv file
    """

    if video.suffixes[-2:] == ['new', 'mkv']:
        print("Skipping .new.mkv video, this has probably already been processed and is a mistaken glob:", video)
        return

    # Find our output base name
    if video.suffixes[-2:-1] == ['.orig']:        # /x/y/name.z.orig.mkv
        base = video.name.rsplit('.', 2)[0]       # /x/y/name.z
        output = video.parent / (base+'.new.mkv') # /x/y/name.z.new.mkv
    else:
        output = video.with_suffix('.new.mkv')

    merge_files = [ ]

    def cache_output(output, regen=False):
        """Cache output, re-gen only if needed.

        If output already exists: return subs from that output
        If output doesn't exist: run wrapped function, save to that output, return generated subs."""
        def tmp(f):
            if output.exists() and not regen:
                return list(srt.parse(output.read_text()))
            else:
                subs = f()
                output.write_text(srt.compose(subs))
                return subs
        return tmp

    # Whisper
    if args.whisper:
        srt_whisper = video.with_suffix(f'.{args.lang}.srt')
        @cache_output(srt_whisper)
        def subs_whisper():
            return whisper(video, args=args)
        merge_files += ['--language',f'0:{args.lang}', '--track-name', f'0:Whisper {args.lang}',     srt_whisper,]

    # Whisper translate
    if args.whisper_trans:
        srt_whisperT = video.with_suffix(f'.qen.srt')
        @cache_output(srt_whisperT)
        def subs_whisper_translate():
            return whisper(video, translate=True, args=args)
        merge_files += ['--language',f'0:{args.lang}', '--track-name', f'0:Whisper en',     srt_whisperT,]

    # Combine whispers
    if args.whisper and args.whisper_trans:
        srt_whisper_C = video.with_suffix('.mul.srt')
        @cache_output(srt_whisper_C)
        def subs_whisper_C():
            return combine(subs_whisper, subs_whisper_translate, args=args)
        merge_files += ['--language', '0:mul',         '--track-name', f'0:Whisper en+{args.lang}', srt_whisper_C,]

    # Google of whisper
    for argname, name, srtT, srtC, trans_func in [
        ('google_whisper', 'google', 'qeG', 'muG', translate_google),
        ('argos_whisper',  'argos', 'qeR', 'muR', translate_argos),
        ('azure_whisper',  'azure', 'qeZ', 'muZ', translate_azure),
        ]:
        if getattr(args, argname):
            print(f"Running {name.title()} on Whisper transcription")
            # pylint: disable=ignore cell-var-from-loop
            srt_T = video.with_suffix(f'.{srtT}.srt')
            srt_C = video.with_suffix(f'.{srtC}.srt')
            @cache_output(srt_T)
            def subs_T():
                return trans_func(subs_whisper, args=args)
            @cache_output(srt_C)
            def subs_C():
                return combine(remove_newlines(subs_whisper), timeshift(subs_T, -.001), args=args)
            merge_files += ['--language', '0:mul', '--track-name', f'0:Whisper {args.lang} + {name}(whisper{args.lang})', srt_C]

    # Translations of original
    if args.sid_original:
        subs_orig = subs_from_file(video, args.sid_original, args.sid_original_lang)

        # Google of original
        for argname, name, srtT, srtC, trans_func in [
            ('google', 'google', 'qeg', 'mug', translate_google),
            ('argos',  'argos', 'qer', 'mur', translate_argos),
            ('azure',  'azure', 'qez', 'muz', translate_azure),
            ]:
            if getattr(args, argname):
                print(f"Running {name.title()} on Whisper transcription")
                # pylint: disable=ignore cell-var-from-loop
                srt_t = video.with_suffix(f'.{srtT}.srt')
                @cache_output(srt_t)
                def subs_t():
                    return trans_func(subs_orig, args=args)
                srt_c = video.with_suffix(f'.{srtC}.srt')
                @cache_output(srt_c)
                def subs_c():
                    return combine(remove_newlines(subs_orig), timeshift(subs_t, -.001), args=args)
                merge_files += ['--language', '0:mul', '--track-name', f'0:orig + {name}(orig)', srt_c]

    # If we don't want to combine to .new.mkv, return now
    if args.no_new_mkv:
        return

    cmd = [
        'mkvmerge',
        video,
        *merge_files,
        '--output', str(output),
        ]
    print(cmd)
    subprocess.run(cmd, check=True)



def combine(subs1, subs2, *, args):
    """Combine two subs into one.  The second one gets a color."""

    subsnew = srt.sort_and_reindex(itertools.chain(subs1, recolor(subs2, color=args.color)))
    return list(subsnew)


def remove_newlines(subs):
    """Remove newlines in subtitles"""
    subs = copy.deepcopy(list(subs))
    for s in subs:
        s.content = ' '.join(s.content.split('\n'))
    return subs
