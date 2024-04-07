from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from dotenv import load_dotenv
from ebooklib import epub
from email.message import EmailMessage
import feedparser
import hashlib
import json
import lxml.etree as ET
import os
import requests
import smtplib
import time

load_dotenv()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
SMTP_FROM = os.getenv('SMTP_FROM')
SMTP_TO = os.getenv('SMTP_TO')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
SMTP_SERVER = os.getenv('SMTP_SERVER')

OPML_PATH = 'feeds.opml'
CACHE_DIR = 'cache'
MAX_ARTICLES = 25
DAYS_CUTFF = 0.6

TOKENS_USED = 0

if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

def ai_summarize(url):
    """Use OpenAI to summarize the contents."""

    print(f"Summarizing {url}")

    # Check if the content is already cached
    cache = False
    url_hash = hashlib.md5(url.encode()).hexdigest()
    cache_file_path = os.path.join(CACHE_DIR, f"{url_hash}.txt")
    if os.path.exists(cache_file_path):
        cache = True
        with open(cache_file_path, 'r') as file:
            ai_response_json = json.loads(file.read())
            ai_content_json = json.loads(ai_response_json["choices"][0]["message"]["content"])["responseSchema"]
            file_date = os.path.getmtime(cache_file_path)
            ai_content_json['cache'] = datetime.fromtimestamp(file_date).strftime('%Y-%m-%d %H:%M')
            print(f"=> Using cache {cache_file_path}")
            return ai_content_json

    # Fetch the content and pull out just the text
    soup_text = ""
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
        soup_text = soup.text
    except requests.exceptions.RequestException as e:
        print(f"=> Error fetching content: {e}")
        return f"Error fetching content from {url}: {e}"

    # Trim the content if too big
    # TODO Count tokens and concat if needed
    is_trimmed = False
    max_tokens = 16385
    average_characters_per_token = 4
    safe_character_limit = (max_tokens * average_characters_per_token) - (4000*4)

    if len(soup_text) > safe_character_limit:
        print(f"=> Trimmed content. Length: {len(soup_text)} characters.")
        soup_text = soup_text[:safe_character_limit]
        is_trimmed = True

    # Use OpenAI chat API to summarize the content
    print(f"=> Contacting AI")

    # Retry if the response is not 200
    while True:
        ai_response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-3.5-turbo",
                "response_format": { "type": "json_object" },
                "messages": [
                    {"role": "system", "content": "You are a helpful research assistant tasked with summarizing online content."},
                    {"role": "user", "content": "Please provide a summary of the content provided using abstractive techniques. Ignore advertising content. Try to limit the summary to no more than 1000 characters and 4-6 bullet points."},
                    {"role": "user", "content": 'Respond with json using the provided schema for your response. The abstract should be 1-2 sentences and you can add additional bullets as needed.\n\n{"responseSchema":{"title":"string","author":"string","datePublished":"date","abstract":"string","summary":[{"bullet":"string"},{"bullet":"string"},{"bullet":"string"}]}}'},
                    {"role": "user", "content": f"<content>\n{soup_text}\n</content>"},
                ]
            },
        )

        if ai_response.status_code == 200:

            # Get the number of tokens used
            global TOKENS_USED
            TOKENS_USED += ai_response.json()['usage']['total_tokens']

            ai_content = ai_response.json()["choices"][0]["message"]["content"]

            ai_content_json = {}
            # Test if the content is json
            try:
                ai_content_json = json.loads(ai_content)["responseSchema"]
            except Exception:
                time.sleep(0.5)

            # Process the JSON content if needed
            if "abstract" not in ai_content_json or \
                "summary" not in ai_content_json or \
                "bullet" not in ai_content_json["summary"][0]:

                print(f"Invalid JSON response. Retrying.")
                time.sleep(0.5)
            else:
                # Cache the content
                url_hash = hashlib.md5(url.encode()).hexdigest()
                cache_file_path = os.path.join(CACHE_DIR, f"{url_hash}.txt")
                with open(cache_file_path, 'w') as file:
                    json.dump(ai_response.json(), file, indent=2)
                return ai_content_json

        else:
            # TODO Better handling for rate limiting and length
            print(f"Error summarizing content. {ai_response.status_code}: {ai_response.text}")
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

            # Check that article published date is within a certain cutoff
            cutoff_date = datetime.now() - timedelta(days=DAYS_CUTFF)
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

    content = f'<h2>{article["title"]}</h2>'
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

    # TODO Iterate through the ai_summary and create the HTML
    ai_summary = article['ai_summary']
    if type(ai_summary) == str:
        content += f"<p>{ai_summary}</p>"
    else:
        content += "<p>\n"
        if 'cache' in ai_summary:
            content += f"(Cached {ai_summary['cache']}) "
        content += f"{ai_summary['abstract']}</p>\n"
        content += "<p><ul>\n"
        for bullet in ai_summary["summary"]:
            try:
                content += f"<li>{bullet['bullet']}</li>\n"
            except Exception:
                content += f"<li>{bullet}</li>\n"
        content += "</ul></p>\n"

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

        content += "<p><ul>"

        for article in feed['articles']:
            content += f"<li><a href='{article['filename']}'>{article['title']}</a></li>"

        content += "</ul></p>"

    return content


def create_epub(opml, feeds):

    number_feeds = len(feeds)

    # title = f"{opml['title']} - {datetime.now().strftime('%B %-d, %Y %-I:%M %p')}"
    title = f"Makepub - {datetime.now().strftime('%B %-d, %Y %-I:%M %p')}"

    book = epub.EpubBook()
    book.set_title(title)
    book.set_identifier('makepub' + str(int(time.time())))
    book.set_language('en')
    book.add_author('Makepub')
    book.add_metadata('calibre', 'series', 'Makepub')

    # Add the stylesheet
    nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css")
    nav_css.content=open('nav.css', 'r').read()
    book.add_item(nav_css)

    # Prepare to create the feed sections and articles
    spine_items = ['nav']  # Initial 'nav' for eBook navigation
    toc_items = []

    # Iterate over the feeds dictionary
    for i, (feed_title, feed) in enumerate(feeds.items(), start=1):

        number_articles = len(feed['articles'])

        if number_articles > 0:

            # Create the feed content
            feed_epub = epub.EpubHtml(title=feed_title, file_name=feed['filename'], lang='en')
            feed_epub.content = create_feed_content(feed_title, feed, number_feeds)
            feed_epub.add_item(nav_css)

            # Add to the appropriate lists
            book.add_item(feed_epub)
            spine_items.append(feed_epub) # type: ignore
            toc_items.append(feed_epub)

            for j, article in enumerate(feed['articles'], start=1):

                # Create a chapter file for each article
                article_epub = epub.EpubHtml(title=article['title'], file_name=article['filename'], lang='en')
                article_epub.content = create_article_content(j, number_articles, article, i, number_feeds, feed_title)
                article_epub.add_item(nav_css)

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

    if not SMTP_PASSWORD or not SMTP_FROM or not SMTP_TO or not SMTP_SERVER:
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
        with smtplib.SMTP_SSL(SMTP_SERVER, 465) as smtp:
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
