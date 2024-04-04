# makepub

Makes an EPub file out of an RSS OPML. Each RSS feed is added as a chapter in the EPub file. The title of the chapter is the title of the feed. The articles of each RSS feed is added as a chapter with a summary generated using the OpenAI GPT-3 API.

## Setup

Uses the [OPML format](https://en.wikipedia.org/wiki/OPML) that many RSS readers can export. A sample file, `sample_feeds.opml` is provided in the repo. To use it, rename (or copy) it to `feeds.opml`. You can directly edit the file.

You also need to set the `OPENAI_API_KEY` environment variable to your OpenAI API key. Or set it in a file named '.env' in the same directory as the script.

## Usage

```bash
python makepub.py
```

This will create an EPub file in the same directory. You can open this file in any EPub reader.
