from bs4 import BeautifulSoup
from datetime import datetime
from dotenv import load_dotenv
from ebooklib import epub
from readability.readability import Document
import feedparser
import lxml.etree as ET
import os
import requests
import time


load_dotenv()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

OPML_PATH = 'makepub.opml'


def read_opml(opml_path):
    data = {'title': None, 'feeds': []}
    tree = ET.parse(opml_path)
    root = tree.getroot()
    data['title'] = root.find('.//head/title').text

    for category in root.findall('.//outline[@text]'):
        for feed in category.findall('.//outline[@type="rss"]'):
            data['feeds'].append({
                'category': category.get('title'),
                'title': feed.get('title'),
                'description': feed.get('description', ''),
                'htmlUrl': feed.get('htmlUrl'),
                'xmlUrl': feed.get('xmlUrl'),
            })

    return data


def fetch_feeds(opml):
    """Fetches the feeds and articles."""

    feeds_content = {}

    for i, feed in enumerate(opml['feeds'], start=1):

        print(f"Fetching {feed['title']}...")
        response = requests.get(feed['xmlUrl'])
        articles = []
        feed_data = feedparser.parse(response.content)

        # TODO Limit to first 3 entries for testing
        for j, entry in enumerate(feed_data.entries[:3], start=1):

            article = {
                'title': entry.title,
                'link': entry.link,
                # 'description': entry.description,
                'published': entry.published_parsed,
                'index': j,
                'filename': f'article_{i}_{j}.xhtml',
            }
            if 'author' in entry:
                article['author'] = entry.author

            articles.append(article)

        feeds_content[feed['title']] = {
            'articles': articles,
            'index': i,
            'filename': f'feed_{i}.xhtml',
        }

    return feeds_content


def create_toc(title, articles):
    """Create a Table of Contents for the EPUB."""
    # toc = '<nav xmlns:epub="http://www.idpf.org/2007/ops" epub:type="toc">'
    toc = "<?xml version='1.0' encoding='utf-8'?>\n"
    toc += '<!DOCTYPE html>\n'
    toc += '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">\n'
    toc += '<head>\n'
    toc += f"<title>{title}</title>\n"
    toc += '</head>\n'
    toc += '<body>\n'
    toc += '<nav epub:type="toc" id="id" role="doc-toc">\n'
    toc += '<h2>Table of Contents</h2>\n'
    toc += '<ol>\n'
    for feed_title, articles in articles.items():
        toc += f'<li><a href="{articles["filename"]}">{feed_title}</a></li>\n'
        toc += '<ol>'
        for article in articles['articles']:
            toc += f'<li><a href="{article["filename"]}">{article["title"]}</a></li>\n'
        toc += '</ol>\n'
    toc += '</ol>\n'
    toc += '</nav>\n'
    toc += '</body>\n'
    toc += '</html>\n'

    print(toc)
    return toc


def create_epub(opml, feeds):

    title = opml['title'] + ' - ' + datetime.now().strftime('%B %-d, %Y')

    book = epub.EpubBook()
    book.set_title(title)

    # Create a custom nav.xhtml
    # nav_item = epub.EpubItem(
    #     uid='nav',
    #     file_name='nav.xhtml',
    #     media_type='application/xhtml+xml')
    # nav_item.content = create_toc(title, articles)
    # book.add_item(nav_item)

    spine_items = ['nav']  # Initial 'nav' for eBook navigation
    toc_items = []

    # Iterate over the articles dictionary
    for i, (feed_title, feed) in enumerate(feeds.items()):

        # Create the feed content
        feed_epub = epub.EpubHtml(title=feed_title, file_name=feed['filename'], lang='en')
        feed_epub.content = f'<h1>{feed_title.upper()}</h1>'
        book.add_item(feed_epub)
        spine_items.append(feed_epub)
        toc_items.append(feed_epub)

        for j, article in enumerate(feed['articles']):

            # Create a chapter file for each article
            article_epub = epub.EpubHtml(title=article['title'], file_name=article['filename'], lang='en')
            article_epub.content = f"<h2>{article['title']}</h2>"
            if 'published' in article:
                article_epub.content += f"<p>{time.strftime('%B %d, %Y, %I:%M %p', article['published'])}</p>"
            if 'author' in article:
                article_epub.content += f"<p>{article['author']}</p>"
            if 'link' in article:
                article_epub.content += f"<p><a href='{article['link']}'>Full Article</a></p>"

            # Add to the appropriate lists
            book.add_item(article_epub)
            spine_items.append(article_epub)
            toc_items.append(article_epub)


    # Setting the table of contents and spine
    book.toc = toc_items

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine_items

    # Write the EPUB file
    epub.write_epub(f"{title}.epub", book, {})
    return f"{title}.epub"


def main():

    opml = read_opml(OPML_PATH)
    feeds = fetch_feeds(opml)
    epub_file = create_epub(opml, feeds)
    print(f"EPUB created: {epub_file}")


# Main execution here
if __name__ == '__main__':
    main()
