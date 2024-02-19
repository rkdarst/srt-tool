#!/usr/bin/env python3

"""Combine srt files and/or generate them with whisper.
"""
import argparse
import copy
import datetime
import io
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

import srt

__version__ = '0.1.0'

WHISPER_ARGS = [
    '--compute_type=float32',  # makes it work on CPUs
    '--threads=8',
    '--condition_on_previous_text=False',  # improves quality a bit
    ]


def main():
    """Main program logic: split by sub-command.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--color', default='#87cefa', help='Default %(default)s')
    parser.add_argument('--lang', default='fi', help='Default %(default)s')
    parser.add_argument('--model', default='large-v3', help='Default %(default)s')

    subparsers = parser.add_subparsers()

    sp_auto = subparsers.add_parser('auto', help="Transcribe, translate, and combine subs, make new .mkv file.  If extension is .orig.mkv, output is .new.mkv, otherwise it is .new.mkv replacing the last portion.")
    sp_auto.add_argument('video', nargs='+', type=Path)
    sp_auto.add_argument('--no-new-mkv', action='store_true')
    sp_auto.add_argument('--re-combine', action='store_true', help="Recombine to .xx.srt, .new.mkv even if they already exist.")
    sp_auto.add_argument('--sid-original', help="Original subtitle id for translation.  If given without --sid-original-lang, this is the subtitle track number.  If given with that option, it is relative to all subtitles of thet language (and can be negative to say 'the last one'")
    sp_auto.add_argument('--sid-original-lang', help="Original subtitle id for translation.  Use ffprobe to see what the options are.")
    sp_auto.add_argument('--argos', action='store_true', default=False,
                         help="Argos translate the original subtitles, requires --sid-original.")
    sp_auto.add_argument('--google', action='store_true',
                         help="Google translate (requires manual interaction), requires --sid-original.")
    sp_auto.add_argument('--azure', action='store_true',
                         help="Translate with Azure.  Set AZURE_KEY.")
    sp_auto.set_defaults(auto=True)

    sp_single = subparsers.add_parser('simple', help="Transcribe to *.srt (no language code in filename)")
    sp_single.add_argument('video', nargs='+', type=Path)
    sp_single.set_defaults(simple=True)

    sp_combine = subparsers.add_parser('combine', help='combine two srt files, coloring the second one')
    sp_combine.add_argument('srt1', type=Path)
    sp_combine.add_argument('srt2', type=Path)
    sp_combine.add_argument('srtout', type=Path)

    sp_trs = subparsers.add_parser('transcribe', help='transcribe to *.LANG.srt')
    sp_trs.add_argument('video', nargs='+', type=Path)
    sp_trs.set_defaults(transcribe=True)

    sp_trl = subparsers.add_parser('translate', help='translate to (english) *.ex.srt')
    sp_trl.add_argument('video', nargs='+', type=Path)
    sp_trs.set_defaults(translate=True)

    args = parser.parse_args()
    print(args)

    # Simple mode
    if hasattr(args, 'simple'):
        for video in args.video:
            whisper(video, output=video.with_suffix('.srt'), args=args)
    # Combine
    elif hasattr(args, 'srtout'):
        combine(args.srt1, args.srt2, args.srtout, args=args)
    # Transcribe
    elif hasattr(args, 'transcribe'):
        for video in args.video:
            whisper(video, output=video.with_suffix(f'.{args.lang}.srt'), args=args)
    # Translate
    elif hasattr(args, 'translate'):
        for video in args.video:
            whisper(video, output=video.with_suffix('.qen.srt'), translate=True, args=args)
    # Default = auto: trs + trl + combine + make new mkv
    else:
        whisper_auto(args=args)



def whisper(video, output, translate=False, *, args):
    """Run whisper with specifid input/output/arguments."""
    if Path(output).exists():
        return
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
        shutil.copyfile(Path(tmpdir)/(Path('file:'+str(video)).stem+'.srt'),
                        output)



def recolor(subs, color):
    """Iterate through srt subs, applying a color to all"""
    for s in subs:
        s.content = '\n'.join(f'<font color="{color}">{x}</font>' for x in s.content.split('\n'))
        yield s


def timeshift(subs, shift=0.001):
    for s in subs:
        s.start += datetime.timedelta(seconds=shift)
        s.end   += datetime.timedelta(seconds=shift)
        yield s

def batched(iter_, n):
    i = 0
    while i < len(iter_):
        yield iter_[i:i+n]
        i += n


def srts_from_file(video, track, track_language=None):
    """Grab srt subtitles from a file.

    `track` is the subtitle track ID (starting from 0 for the first subtitle track).

    `track_language` adjusts the meaning of `track.  If given, only
    consider tracks matching that language.  Select the relevant track
    from those.  0 means first, and -1 means last.
    """
    # Figure out which track we want
    cmd = [
        'ffprobe', 'file:'+str(video),
        '-print_format', 'json', '-show_format', '-show_streams',
        ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, check=True)
    data = json.loads(p.stdout.decode())
    data = data['streams']

    if isinstance(track, str) and ':' in track:
        track_language, track = track.split(':', 1)
    track = int(track)
    if track_language:
        data = [x for x in data if x['codec_type']=='subtitle' and x['tags']['language'] == track_language]
        try:
            track = data[track]['index']
        except IndexError as exc:
            raise RuntimeError(f"Bad subtitle track/track-lang combination {track} and {track_language} in {video}.  Try ffprobe on the file to see the streams.") from exc
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
    return p.stdout.decode()



def translate(subs, *, args):
    cmd = [
        '/home/rkdarst/sys/argostranslate/argospipe.py',
        args.lang,
        'en',
        ]
    with subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, encoding='utf8') as p:
        (child_stdin, child_stdout) = (p.stdin, p.stdout)
        speaker_re = re.compile(r'((?:\s|^)-)(?=\w)', re.MULTILINE)
        all_subs = [ ]

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
            yield s
            all_subs.append(json.dumps(content))


def translate_google(subs):

    #subs = list(srt.parse(srtb))
    #for s in subs:
    #    s.content = ' '.join(s.content.split('\n'))
    #srtb = srt.compose(subs).encode()

    #srtb = srtb.split(b'\n\n')
    #i = 0
    #srtb_new = []

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
            print(f"Copying {len(stdin)}b... paste into Google Translate")


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
                print("failure parsing, try agani")
                continue

    return subs

    #while i < len(srtb):
    #    next = [ ]
    #    size = 0
    #    while size < 4750 and i < len(srtb):
    #        next.append(srtb[i])
    #        size += len(srtb[i])
    #        i += 1
    #    stdin = b'\n\n'.join(next)
    #    subprocess.run(['xclip', '-in'], input=stdin, check=True)
    #    subprocess.run(['xclip', '-in', '-selection', 'clipboard'], input=stdin, check=True)
    #    print(f"Copying {len(stdin)}b... paste into Google Translate")
    #
    #    while True:
    #        time.sleep(1)
    #        print("Waiting for you to copy the output translation...")
    #        p = subprocess.run(['xclip', '-out', '-selection', 'clipboard'], stdout=subprocess.PIPE, check=True)
    #        stdout = p.stdout
    #        if stdout != stdin:
    #            break
    #    print(stdout.decode())
    #    srtb_new.append(stdout)
    #srtb_new = b'\n\n'.join(srtb_new)
    #return srtb_new.decode()


def translate_azure(subs):

    key = os.environ['AZURE_KEY']
    import requests
    #class AzureAuth(requsets.auth.AuthBase):
    #    def __init__(self, key):
    #        self.key = key
    def auth(r): #def __call__(self, r):
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
            params={'api-version': '3.0', 'from': 'fi', 'to': ['en']},
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




def whisper_auto(args):
    """Automatically run translate/transcribe/combine to new file.

    - Whisper transcribe
    - Whisper translate
    - Combine them into one srt file
    - Create a .new.mkv file
    """

    for video in args.video:
        if video.suffixes[-2:] == ['new', 'mkv']:
            print("Skipping .new.mkv video:", video)
            continue
        if video.suffixes[-2:-1] == ['.orig']:        # /x/y/name.z.orig.mkv
            base = video.name.rsplit('.', 2)[0]       # /x/y/name.z
            output = video.parent / (base+'.new.mkv') # /x/y/name.z.new.mkv
        else:
            output = video.with_suffix('.new.mkv')
        srt1 = video.with_suffix(f'.{args.lang}.srt')
        srt2 = video.with_suffix('.qen.srt')
        srtout = video.with_suffix('.mul.srt')
        if output.exists() and not args.re_combine:
            continue
        if not output.exists():
            if not srt1.exists(): whisper(video, srt1, args=args) # transcribe
            if not srt2.exists(): whisper(video, srt2, translate=True, args=args) # translate
        combine(srt1,
                srt2,
                srtout,
                args=args)

        if args.no_new_mkv:
            return

        merge_extra = [ ]
        if args.sid_original:
            srts_orig = srts_from_file(video, args.sid_original, args.sid_original_lang)

            srtout2 = video.with_suffix('.mu2.srt')
            combine(srt.parse(srts_orig), srt2, srtout2, args=args)
            merge_extra.extend(['--language', '0:mul', '--track-name', '0:Whisper qen+orig', srtout2])

            if args.argos:
                srtout3 = video.with_suffix('.mu3.srt')
                subs3 = translate(srt.parse(srts_orig), args=args)
                combine(remove_newlines(srt.parse(srts_orig)), timeshift(subs3, -.001), srtout3, args=args)
                merge_extra.extend(['--language', '0:mul',  '--track-name', '0:argos(orig)+orig', srtout3])

            if args.google:
                srtout_g = video.with_suffix('.qeg.srt')
                if not srtout_g.exists():
                    srtb_g = srt.compose(translate_google(srt.parse(srts_orig)))
                    open(srtout_g, 'w').write(srtb_g)
                else:
                    srtb_g = open(srtout_g, 'r').read()
                srtout4 = video.with_suffix('.mu4.srt')
                combine(remove_newlines(srt.parse(srts_orig)), timeshift(srt.parse(srtb_g), -.001), srtout4, args=args)
                merge_extra.extend(['--language', '0:mul', '--track-name', '0:google(orig)+orig', srtout4])

            if args.azure:
                srtout_z = video.with_suffix('.qez.srt')
                if not srtout_z.exists():
                    subs_z = translate_azure(srt.parse(srts_orig))
                    srtb_z = srt.compose(subs_z)
                    open(srtout_z, 'w').write(srtb_z)
                else:
                    subs_z = srt.parse(open(srtout_z, 'r').read())
                srtout5 = video.with_suffix('.mu5.srt')
                combine(remove_newlines(srt.parse(srts_orig)), timeshift(subs_z, -.001), srtout5, args=args)
                merge_extra.extend(['--language', '0:mul', '--track-name', '0:azure(orig)+orig', srtout5])


        cmd = [
            'mkvmerge',
            video,
            '--original-flag', '0',
            '--language',f'0:{args.lang}', '--track-name', f'0:Whisper {args.lang}',     srt1,
            '--language', '0:qen',         '--track-name',  '0:Whisper qen',             srt2,
            '--language', '0:mul',         '--track-name', f'0:Whisper qen+{args.lang}', srtout,
            *merge_extra,
            '--output', str(output),
            ]
        print(cmd)
        subprocess.run(cmd, check=True)



def combine(subs1, subs2, subsout, *, args):
    """Combine two srt files into one.  The second one gets a color."""

    if isinstance(subs1, (str, Path)):
        subs1 = srt.parse(open(subs1, encoding='utf8'))
    if isinstance(subs2, (str, Path)):
        subs2 = srt.parse(open(subs2, encoding='utf8'))
    subsnew = srt.sort_and_reindex(itertools.chain(subs1, recolor(subs2, color=args.color)))

    if isinstance(subsout, (str, Path)):
        open(subsout, 'w', encoding='utf8').write(srt.compose(subsnew))
    else:
        return subsnew


def remove_newlines(subs):
    """Remove newlines in subtitles"""
    subs = copy.deepcopy(list(subs))
    for s in subs:
        s.content = ' '.join(s.content.split('\n'))
    return subs
