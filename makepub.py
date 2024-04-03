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

def create_article_content(article_index, number_articles, article, feed_index, number_feeds, feed_title):

    content = f"<h2>{article['title']}</h2>"
    if 'published' in article:
        content += f"<p>{time.strftime('%B %d, %Y, %I:%M %p', article['published'])}</p>"
    if 'author' in article:
        content += f"<p>{article['author']}</p>"
    if 'link' in article:
        content += f"<p><a href='{article['link']}'>Full Article</a></p>"

    # Add navigation markers
    # Navigation to the previous article
    if article_index == 1:
        # If first article of a feed, go to the feed page
        prev_filename = f'feed_{feed_index}.xhtml'
    else:
        prev_filename = f'article_{feed_index}_{article_index - 1}.xhtml'

    content += f"<p><a href='{prev_filename}'>&lt;&lt; Previous</a> | "

    content += f"<a href='nav.xhtml'>{feed_title} ({article_index}/{number_articles})</a>"

    # Navigation to the next article
    if article_index < number_articles:
        next_filename = f'article_{feed_index}_{article_index + 1}.xhtml'
    else:
        if feed_index == number_feeds:
            next_filename = 'nav.xhtml'
        else:
            next_filename = f'feed_{feed_index + 1}.xhtml'

    content += f" | <a href='{next_filename}'>Next &gt;&gt;</a></p>"

    return content


def create_feed_content(feed_title, feed):

    content = f"<h1>{feed_title.upper()}</h1>"
    content += f"<p>{datetime.now().strftime('%B %-d, %Y')}</p>"

    if len(feed['articles']) == 0:

        content += "<p>No articles today.</p>"

    else:

        content += "<ul>"

        for article in feed['articles']:
            content += f"<li><a href='{article['filename']}'>{article['title']}</a></li>"

        content += "</ul>"

    return content


def create_epub(opml, feeds):

    title = opml['title'] + ' - ' + datetime.now().strftime('%B %-d, %Y')

    book = epub.EpubBook()
    book.set_title(title)
    book.set_language('en')

    spine_items = ['nav']  # Initial 'nav' for eBook navigation
    toc_items = []

    number_feeds = len(feeds)

    # Iterate over the articles dictionary
    for i, (feed_title, feed) in enumerate(feeds.items(), start=1):

        # Create the feed content
        feed_epub = epub.EpubHtml(title=feed_title.upper(), file_name=feed['filename'], lang='en')
        feed_epub.content = create_feed_content(feed_title, feed)
        book.add_item(feed_epub)
        spine_items.append(feed_epub)
        toc_items.append(feed_epub)

        number_articles = len(feed['articles'])

        for j, article in enumerate(feed['articles'], start=1):

            # Create a chapter file for each article
            article_epub = epub.EpubHtml(title=article['title'], file_name=article['filename'], lang='en')
            article_epub.content = create_article_content(j, number_articles, article, i, number_feeds, feed_title)

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
