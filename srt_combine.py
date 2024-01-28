#!/usr/bin/env python3

"""Combine srt files and/or generate them with whisper
"""
import argparse
import itertools
from pathlib import Path
import shutil
import subprocess
import tempfile

import srt

__version__ = '0.1.0'


def whisper(video, output, translate=False, *, args):
    if Path(output).exists():
        return
    with tempfile.TemporaryDirectory(prefix='whisper-') as tmpdir:
        cmd = [
            'whisper-ctranslate2',
            'file:'+str(video),
            '--compute_type=float32',
            '--output_format=srt',
            '--language='+args.lang,
            '--model='+args.model,
            '--threads=8', '--condition_on_previous_text=False',
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--color', default='#87cefa')
    parser.add_argument('--lang', default='fi')
    parser.add_argument('--model', default='large-v3')
    parser.add_argument('--no-new-mkv', action='store_true')
    parser.add_argument('video', nargs='+', type=Path)

    subparsers = parser.add_subparsers()

    parser_combine = subparsers.add_parser('combine')
    parser_combine.add_argument('srt1', type=Path)
    parser_combine.add_argument('srt2', type=Path)
    parser_combine.add_argument('srtout', type=Path)

    parser_trs = subparsers.add_parser('transcribe')
    parser_trs.add_argument('video', nargs='+', type=Path)
    parser_trs.set_default(transcribe=True)

    parser_trl = subparsers.add_parser('translate')
    parser_trl.add_argument('video', nargs='+', type=Path)
    parser_trs.set_default(translate=True)


    args = parser.parse_args()
    print(args)

    # Combine
    if hasattr(args, 'srtout'):
        combine(args.srt1, args.srt2, args.srtout, args=args)
    # Transcribe
    if hasattr(args, 'transcribe'):
        for video in args.video:
            whisper(video, output=video.with_suffix(f'.{args.lang}.srt'), args=args)
    # Translate
    if hasattr(args, 'translate'):
        for video in args.video:
            whisper(video, output=video.with_suffix('.ex.srt'), translate=True, args=args)
    # Default: trs + trl + combine + make new mkv
    else:
        whisper_auto(args=args)

def whisper_auto(args):

    for video in args.video:
        output = video.with_suffix('.new.mkv')
        if output.exists():
            print('Already exists:', output)
            continue

        srt1 = video.with_suffix(f'.{args.lang}.srt')
        srt2 = video.with_suffix('.ex.srt')
        srtout = video.with_suffix('.xx.srt')
        whisper(video, srt1, args=args) # transcribe
        whisper(video, srt2, translate=True, args=args) # translate
        combine(srt1, srt2, srtout, args=args)

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

    subs1 = srt.parse(open(srt1))
    subs2 = srt.parse(open(srt2))
    subsnew = srt.sort_and_reindex(itertools.chain(subs1, recolor(subs2, color=args.color)))

    open(srtout, 'w').write(srt.compose(subsnew))
