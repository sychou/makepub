# TODOs
# - Add error handling for OpenAI API rate limiting
# - Add counter of how many tokens are used

from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from dotenv import load_dotenv
from ebooklib import epub
import feedparser
import lxml.etree as ET
import os
import requests
import time
import hashlib
import smtplib
from email.message import EmailMessage

load_dotenv()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
SMTP_FROM = os.getenv('SMTP_FROM')
SMTP_TO = os.getenv('SMTP_TO')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')

OPML_PATH = 'feeds.opml'
CACHE_DIR = 'cache'
MAX_ARTICLES = 25

if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

def ai_summarize(url):
    """Use OpenAI to summarize the contents."""

    print(f"Summarizing {url}...")

    # Check if the content is already cached
    url_hash = hashlib.md5(url.encode()).hexdigest()
    cache_file_path = os.path.join(CACHE_DIR, f"{url_hash}.txt")
    if os.path.exists(cache_file_path):
        with open(cache_file_path, 'r') as file:
            print(f"=> Using cached content for {url}")
            return file.read()

    content = "Nada"
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
        content = soup.text
    except requests.exceptions.RequestException as e:
        print(f"=> Error fetching content from {url}: {e}")
        content = f"Error fetching content from {url}: {e}"

    if len(content) < 1000:
        print("=> Returning all text as summary.")
        return content

    # TODO Count tokens and concat if needed
    is_trimmed = False
    max_tokens = 16385
    average_characters_per_token = 4

    # Calculate safe character limit
    safe_character_limit = (max_tokens * average_characters_per_token) - (4000*4)

    if len(content) > safe_character_limit:
        print(f"=> Trimmed content. Length: {len(content)} characters.")
        content = content[:safe_character_limit]
        is_trimmed = True

    # Use OpenAI chat API to summarize the content
    print(f"=> Summarizing content with AI")
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": f"Please write a concise (under 2000 characters) and comprehensive summary of the following using bullet points. When responding, use HTML.\n\n{content}"},
            ]
        },
    )
    if response.status_code == 200:
        content = response.json()["choices"][0]["message"]["content"]

        # TODO Clean up common AI artifacts such as the ``` markers and extra <h1> tags

        if is_trimmed:
            content = "<strong>AI Summary (content trimmed):</strong> " + content
        else:
            content = "<strong>AI Summary:</strong> " + content

        # Cache the content
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_file_path = os.path.join(CACHE_DIR, f"{url_hash}.txt")
        with open(cache_file_path, 'w') as file:
            file.write(content)

        return content
    else:
        # TODO Better handling for rate limiting and length
        print(f"Error summarizing content. {response.status_code}: {response.text}")
        return None


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

        for j, entry in enumerate(feed_data.entries[:MAX_ARTICLES], start=1):

            # Check that article published date is within the last 24 hours
            cutoff_date = datetime.now() - timedelta(days=1)
            published_date = datetime.fromtimestamp(time.mktime(entry.published_parsed))

            if published_date > cutoff_date:

                ai_summary = ai_summarize(entry.link)
                time.sleep(1)

                article = {
                    'title': entry.title,
                    'link': entry.link,
                    # 'description': entry.description,
                    'published': published_date,
                    'index': j,
                    'filename': f'article_{i}_{j}.xhtml',
                    'ai_summary': ai_summary,
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
        content += f"<p>{article['published'].strftime('%B %d, %Y, %I:%M %p')}<br>"
    if 'author' in article:
        content += f"{article['author']}</p>"

    # Add navigation markers
    # Navigation to the previous article
    if article_index == 1:
        # If first article of a feed, go to the feed page
        prev_filename = f'feed_{feed_index}.xhtml'
    else:
        prev_filename = f'article_{feed_index}_{article_index - 1}.xhtml'

    content += f"<p><a href='{prev_filename}'>&lt;&lt; Previous</a> | "

    content += f"<a href='feed_{feed_index}.xhtml'>{feed_title} ({article_index}/{number_articles})</a>"

    # Navigation to the next article
    if article_index < number_articles:
        next_filename = f'article_{feed_index}_{article_index + 1}.xhtml'
    else:
        if feed_index == number_feeds:
            next_filename = 'nav.xhtml'
        else:
            next_filename = f'feed_{feed_index + 1}.xhtml'

    content += f" | <a href='{next_filename}'>Next &gt;&gt;</a></p>"

    content += f"<p>{article['ai_summary']}</p>"

    if 'link' in article:
        content += f"<p><a href='{article['link']}'>Full Article</a></p>"

    return content


def create_feed_content(feed_title, feed, number_feeds):

    content = f"<h1>{feed_title}</h1>"
    # content += f"<p>{datetime.now().strftime('%B %-d, %Y')}</p>"

    # Add navigation markers
    if feed['index'] == 1:
        prev_filename = 'nav.xhtml'
    else:
        prev_filename = f'feed_{feed["index"] - 1}.xhtml'

    content += f"<p><a href='{prev_filename}'>&lt;&lt; Previous</a> | "
    content += f"<a href='nav.xhtml'>TOC</a> | "

    if feed['index'] == number_feeds:
        next_filename = 'nav.xhtml'
    else:
        next_filename = f'feed_{feed["index"] + 1}.xhtml'

    content += f"<a href='{next_filename}'>Next &gt;&gt;</a></p>"

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
    book.set_identifier('makepub')
    book.set_language('en')
    book.add_author('Makepub')

    spine_items = ['nav']  # Initial 'nav' for eBook navigation
    toc_items = []

    number_feeds = len(feeds)

    # Iterate over the articles dictionary
    for i, (feed_title, feed) in enumerate(feeds.items(), start=1):

        # Create the feed content
        feed_epub = epub.EpubHtml(title=feed_title, file_name=feed['filename'], lang='en')
        feed_epub.content = create_feed_content(feed_title, feed, number_feeds)
        book.add_item(feed_epub)
        spine_items.append(feed_epub) # type: ignore
        toc_items.append(feed_epub)

        number_articles = len(feed['articles'])

        for j, article in enumerate(feed['articles'], start=1):

            # Create a chapter file for each article
            article_epub = epub.EpubHtml(title=article['title'], file_name=article['filename'], lang='en')
            article_epub.content = create_article_content(j, number_articles, article, i, number_feeds, feed_title)

            # Add to the appropriate lists
            book.add_item(article_epub)
            spine_items.append(article_epub) # type: ignore
            # toc_items.append(article_epub)


    # Setting the table of contents and spine
    book.toc = toc_items

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine_items

    # Write the EPUB file
    epub.write_epub(f"{title}.epub", book, {})
    return f"{title}.epub"


def email_epub(epub_file):

    if not SMTP_PASSWORD or not SMTP_FROM or not SMTP_TO:
        print("SMTP variables not set in the environment variables. Epub file not emailed.")
        exit()

    # Generate today's date in the specified format and setup the filename
    current_date = datetime.now().strftime("%B %-d, %Y")

    # Check if file exists
    if not os.path.isfile(epub_file):
        print(f"Error: The file '{epub_file}' was not found.")
        exit()

    # Create the email message
    msg = EmailMessage()
    msg['Subject'] = epub_file
    msg['From'] = SMTP_FROM
    msg['To'] = SMTP_TO
    msg.set_content('Please find attached the document.')

    # Attach the file
    with open(epub_file, 'rb') as f:
        file_data = f.read()
        file_type = 'application/epub+zip'
        msg.add_attachment(file_data, maintype='application', subtype='epub+zip', filename=epub_file)

    # Send the email through GMail's SMTP server
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(SMTP_FROM, SMTP_PASSWORD)
            smtp.send_message(msg)
            print("Email sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")


def main():

    opml = read_opml(OPML_PATH)
    feeds = fetch_feeds(opml)
    epub_file = create_epub(opml, feeds)
    print(f"EPUB created: {epub_file}")
    email_epub(epub_file)


# Main execution here
if __name__ == '__main__':
    main()
