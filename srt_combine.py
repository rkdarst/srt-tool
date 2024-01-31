#!/usr/bin/env python3

"""Combine srt files and/or generate them with whisper.
"""
import argparse
import itertools
from pathlib import Path
import shutil
import subprocess
import tempfile

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

    sp_auto = subparsers.add_parser('auto', help="Transcribe, translate, and combine subs, make new .mkv file")
    sp_auto.add_argument('video', nargs='+', type=Path)
    sp_auto.add_argument('--no-new-mkv', action='store_true')
    sp_auto.add_argument('--re-combine', action='store_true', help="Recombine to .xx.srt, .new.mkv even if they already exist.")
    sp_auto.set_defaults(single=True)

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

    # Single mode
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
            whisper(video, output=video.with_suffix('.ex.srt'), translate=True, args=args)
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



def whisper_auto(args):
    """Automatically run translate/transcribe/combine to new file.

    - Whisper transcribe
    - Whisper translate
    - Combine them into one srt file
    - Create a .new.mkv file
    """

    for video in args.video:
        output = video.with_suffix('.new.mkv')
        srt1 = video.with_suffix(f'.{args.lang}.srt')
        srt2 = video.with_suffix('.en.srt')
        srtout = video.with_suffix('.mul.srt')
        if output.exists() and not args.re_combine:
            continue
        if not output.exists():
            if not srt1.exists(): whisper(video, srt1, args=args) # transcribe
            if not srt2.exists(): whisper(video, srt2, translate=True, args=args) # translate
        combine(srt1, srt2, srtout, args=args)

        if args.no_new_mkv:
            return
        cmd = [
            'mkvmerge',
            video,
            '--original-flag', '0',
            '--language',f'0:{args.lang}', '--track-name', f'0:Whisper {args.lang}',     srt1,
            '--language', '0:eng',         '--track-name',  '0:Whisper en',              srt2,
            '--language', '0:mul',         '--track-name', f'0:Whisper en+{args.lang}',  srtout,
            '--output', str(output),
            ]
        print(cmd)
        subprocess.run(cmd, check=True)



def combine(srt1, srt2, srtout, *, args):
    """Combine two srt files into one.  The second one gets a color."""

    subs1 = srt.parse(open(srt1))
    subs2 = srt.parse(open(srt2))
    subsnew = srt.sort_and_reindex(itertools.chain(subs1, recolor(subs2, color=args.color)))

    open(srtout, 'w').write(srt.compose(subsnew))
