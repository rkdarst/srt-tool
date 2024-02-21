# srt-tool

This does many operations on subtitles, originally intended for
language learning, but now it has many modes that could be useful in
many different cases:
* Combine two srt files into one, coloring one of them.  The original
  use was (original language, translated) at the same time.
* Run Whisper on original files and get videos (with easier to
  remember arguments)
* Send subtitles through Argos (a locally installable open-source
  translator), Google Translate, or Microsoft Translate (Azure)
* Do all the above and automatically combine them.

Example: (if anyone has a public domain Finnish video sample, I can
make an example)

![Screenshot of the "argos translate of original" mode, showing both
Finnash (white) and English (blue) at the same time](testdata/screenshot-1.jpg)


## Installation

`pip install .` or `pip install
https://github.com/rkdarst/srt-combine/archive/refs/heads/master.zip`
.  This installs a `srt-combine` script.

The project does define its dependencies.  One of them is
`whisper-ctranslate2`, and I don't know if it will cleanly install or
run on other computers.  You might need to figure that out yourself.
(In theory it would be compatible with other Whisper implementations,
but whisperx does translation at a paragraph level, which is less
useful for my use case).

Currently Whisper arguments are hard-coded.

TODO: test on more diverse systems and fix dependency handling.



## Usage

There are many different modes.  There is good `--help` for each mode.
Each is run via
```console
$ srt-tool [common-args] SUBCOMMAND [args]
```

Commands that take subtitle files can be defined different ways
* `FILE.srt`: srt files read normally
* `FILE.video`: Take the first subtitle track from this video
* `FILE.video:LANG:N`: Take the `N`th subtitle track of language
  `LANG` from this video.

Videos are specified just as videos.  The argument `--sid-original`
can specify the "original" subtitle track, either as a number `N`, or
`LANG:N` for the `N`th track of that language (the first track is 0).
If `N` is negative, count from the end.

Common arguments:
* `--lang` specifies original language (default `fi`)
* `--model=` is whisper model (default `large-v3`)

`qen` and in general `qeX` is used as language codes of "transcribed
English, not original".


### srt-tool `simple FILE.xxx`

Run whisper on input file, save to `FILE.srt` file.  This is basically
an easier way to run Whisper with the default arguments I need without
remembering them all.

### srt-tool `transcribe FILE.xxx`

Like `simple`, but saves the file to `FILE.LANG.srt`

### srt-tool `translate FILE.xxx`

Like above, but translates to English using Whisper, and saves file to `FILE.LANG.qen`

### srt-tool `combine FILE1.srt FILE2.srt OUTPUT.srt`

Combine the two input srt files, saving to `OUTPUT.srt`.  This
command, and following ones, can accept any subtitle definition as
listed above (specifically including the options to automatically
extract them from a video)

### srt-tool `{argos,google,azure} FILE.srt OUTPUT.srt`

Run the respective translation service on the srt file.  Remember that
this can automatically extract them form a video.

* `argos`: An open-source, locally installable translation engine.
  It's OK.  Requires extra setup that isn't described here.
* `google`: Google Translate.  It doesn't use the API, instead, it
  copies it to the clipboard, which you need to past to Google
  Translate yourself, and then copy the output.  It repeats until it's
  done it all (5000 chars at a time).
* `azure`: Microsoft Translator.  This does use the Azure API and
  needs an API token to be defined in the environment variable
  `AZURE_KEY`.

### srt-tool `auto VIDEO.xxx`

Does all of the above automatically, saves to `FILE.new.mkv`.  (if the
file ends with `.orig.mkv`, replace that `orig` with `new`.  This will
create a bunch of temporary `.srt` files that are next to the video,
which allow the final output to be re-generated without re-computing
everything, if you need to add more options or something.

What happens is controlled by lots of options.  in general, lowercase
is "based on the original" and upper case is "done ":

* `-w`: Whisper transcription
* `-W`: Whisper translation
* if `-w -W`, then also save a combined file of both of them.
* `-r` or `-R`: aRgos translate on original/whisper transcribed.
* `-g` or `-G`: Google translate on original/whisper transcribed
* `-z` or `-Z`: aZure transcription on original/whisper transcribed



## Status and development

One person's toy project.  Parts may be randomly broken if they
haven't been used in a while.  Expect to have to read or change code,
but there has been one big refactoring so it's likely to be maintainable now.
If this is useful for you, ask me and I can formalize it more.
(but if it's useful, ask me to formalize it some).


## Test data

* reittidemo (CC-0): http://urn.fi/urn:nbn:fi:lb-2020112930



## See also

* [mpv](https://mpv.io/) has a `--secondary-sid=N` option that can display a
  second subtitle track (at the top).
* mpv also has [lots of
  extensions](https://github.com/stax76/awesome-mpv), some of which
  are good for language learning or advanced subtitle handling.
