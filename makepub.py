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


def fetch_feeds(feeds):
    """Fetches the feeds and articles."""

    feeds_content = {}

    for i, feed in enumerate(feeds['feeds'], start=1):

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


def create_epub(feeds, articles):
    title = feeds['title'] + ' - ' + datetime.now().strftime('%B %-d, %Y')

    book = epub.EpubBook()
    book.set_title(title)

    # Create a custom nav.xhtml
    nav_item = epub.EpubItem(
        uid='nav',
        file_name='nav.xhtml',
        media_type='application/xhtml+xml')
    nav_item.content = create_toc(title, articles)
    book.add_item(nav_item)

    spine_items = ['nav']  # Initial 'nav' for eBook navigation

    # Iterate over the articles dictionary
    for i, (feed_title, articles) in enumerate(articles.items()):

        for j, article in enumerate(articles['articles']):

            article_title = article['title']
            article_content = f'<h1>{article_title}</h1>'
            if 'published' in article:
                article_content += f"<p>{time.strftime('%B %d, %Y, %I:%M %p', article['published'])}</p>"
            if 'author' in article:
                article_content += f"<p>{article['author']}</p>"
            if 'link' in article:
                article_content += f"<p><a href='{article['link']}'>Full Article</a></p>"

            # Create a chapter file for each article
            epub_chapter = epub.EpubHtml(title=article_title, file_name=article['filename'], lang='en')
            epub_chapter.content = article_content

            book.add_item(epub_chapter)
            spine_items.append(epub_chapter)


    # Setting the table of contents and spine
    # book.toc = tuple(toc_feeds)

    book.add_item(epub.EpubNcx())
    # book.add_item(epub.EpubNav())
    book.spine = spine_items

    # Write the EPUB file
    epub.write_epub(f"{title}.epub", book, {})


def main():

    feeds = read_opml(OPML_PATH)
    # print(feeds)
    articles = fetch_feeds(feeds)
    # print(articles)
    create_epub(feeds, articles)



    # output_path = f"{feeds_info['title']} - {datetime.now().strftime('%B %-d, %Y')}.epub"
    # create_epub_from_opml(feeds_info, output_path)
    # print(f"EPUB created: {output_path}")


# Main execution here
if __name__ == '__main__':
    main()
