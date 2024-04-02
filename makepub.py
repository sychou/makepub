from datetime import datetime
from ebooklib import epub
import feedparser
import lxml.etree as ET
import requests
import time

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

def fetch_feed_content(xmlUrl):
    """Fetches and parses the RSS feed returning title and summary of the first few items."""
    content = []
    response = requests.get(xmlUrl)
    feed = feedparser.parse(response.content)

    for entry in feed.entries[:5]:  # Limit to first 5 entries for brevity
        content_entry = {
            'title': entry.title,
            'link': entry.link,
            'description': entry.description,
            'published': entry.published_parsed,
        }
        if 'author' in entry:
            content_entry['author'] = entry.author

        content.append(content_entry)
    return content

def create_epub_from_opml(feeds_info, output_path):
    book = epub.EpubBook()
    book.set_title(feeds_info['title'])

    # Define CSS style for page breaks
    style = 'body { font-family: Times, serif; margin: 5%; } .page-break { page-break-after: always; }'
    nav_css = epub.EpubItem(uid="style_nav", file_name="style/style.css", media_type="text/css", content=style)
    book.add_item(nav_css)

    spine_items = ['nav']  # Initial 'nav' for eBook navigation
    toc_items = []  # Used for building TOC

    # Iterate over each feed directly from OPML order
    for feed in feeds_info['feeds']:
        print(f"Fetching {feed['title']}...")
        feed_content = fetch_feed_content(feed['xmlUrl'])
        print(f"Found {len(feed_content)} articles.")

        # Start the chapter content for the feed
        feed_chapter_content = f'<h1>{feed["title"]}</h1>'
        for article in feed_content:
            # Separate articles by page breaks instead of horizontal rules
            article_content = f"<div><h2>{article['title']}</h2>"
            if 'published' in article:
                # article_content += f"<p>{article['published']}</p>"
                article_content += f"<p>{time.strftime('%B %d, %Y, %I:%M %p', article['published'])}</p>"
            if 'author' in article:
                article_content += f"<p>{article['author']}</p>"
            if 'link' in article:
                article_content += f"<p>{article['description']}</p>"
                article_content += f"<p><a href='{article['link']}'>Full Article</a></p>"
            article_content += "</div><div class='page-break'></div>"
            feed_chapter_content += article_content

        # Create feed chapter
        feed_filename = f"{feed['title'].replace(' ', '_').replace('/', '_')}.xhtml"
        feed_chapter = epub.EpubHtml(title=feed['title'], file_name=feed_filename, lang='en', content=feed_chapter_content)
        feed_chapter.add_item(nav_css)
        book.add_item(feed_chapter)

        # Update spine and TOC
        spine_items.append(feed_chapter)
        toc_items.append(feed_chapter)

    # Final book setup
    book.toc = toc_items
    book.spine = spine_items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Write the EPUB file
    epub.write_epub(output_path, book, {})

# Main execution here
if __name__ == '__main__':
    opml_path = 'makepub.opml'
    feeds_info = read_opml(opml_path)
    output_path = f"{feeds_info['title']} - {datetime.now().strftime('%B %-d, %Y')}.epub"
    create_epub_from_opml(feeds_info, output_path)
    print(f"EPUB created: {output_path}")
