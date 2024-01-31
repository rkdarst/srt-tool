# srt-combine

Originally, this combined two subtitle files into one, coloring one of
the subtitles.  The point is easy multi-lingual subtitles for use in
learning languages.

But then it grew where it can run Whisper automatically to get those
subtitles.  Then it started to run whisper as a general purpose
wrapper (since its command line arguments are a bit... annoying?  Now
it's my general Whisper wrapper.

Example: (if anyone has a public domain Finnish video sample, I can
make an example)



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



## Usage

`srt-combined` with the following options:

* `auto VIDEO.xxx`: Run whisper to transcribe in `--lang`, run whisper
  to translate to `en`, combine the srt files, create a new
  `VIDEO.new.mkv` video file with all of them (unless you give
  `--no-new-mkv`).  It leaves all the intermediate files.  **This is
  what I usually use**
* `simple FILE.xxx`: run whisper on that input, create a `FILE.srt` file
* `combine SRT1 SRT2 SRTOUT`: combine the first two into the output.
  The second gets colored.
* `transcribe FILE.xxx ...`: transcribe to `FILE.{lang}.srt`.  **This
  is a simple whisper wrapper**
* `translate FILE.xxx ...`: transcribe to English at `FILE.ex.srt`.

Common options:
* `--lang` is input language (default `fi`)
* `--model=` is whisper model (default `large-v3`)

The code may be more up to date than the above.



## Status and development

One person's toy project.  Parts may be randomly broken if they
haven't been used in a while.  Expect to have to read or change code
(but if it's useful, ask me to formalize it some).


## See also

* [mpv](https://mpv.io/) has a `--secondary-sid=N` option that can display a
  second subtitle track (at the top).
* mpv also has [lots of
  extensions](https://github.com/stax76/awesome-mpv), some of which
  are good for language learning or advanced subtitle handling.
