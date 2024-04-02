from bs4 import BeautifulSoup
from datetime import datetime
from dotenv import load_dotenv
from ebooklib import epub
from readability.readability import Document
import os
import requests
import xml.etree.ElementTree as ET

load_dotenv()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

def fetch_content(url):
    """Fetch content from a URL and handle errors."""
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching content from {url}: {e}")
        return None


def ai_summarize(content):
    """Use OpenAI to summarize the contents."""
    if len(content) < 1000:
        soup = BeautifulSoup(content, 'lxml')
        return soup.text

    # TODO Count tokens and concat if needed
    is_trimmed = False
    max_tokens = 16385
    average_characters_per_token = 4

    # Calculate safe character limit
    safe_character_limit = (max_tokens * average_characters_per_token) - (2100*4)

    if len(content) > safe_character_limit:
        print(f"Trimmed content. Length: {len(content)} characters.")
        content = content[:safe_character_limit]
        is_trimmed = True

    # Use OpenAI chat API to summarize the content
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
                {"role": "user", "content": f"Can you write a concise and comprehensive summary of the following\n\n:{content}"},
            ]
        },
    )
    if response.status_code == 200:
        content = response.json()["choices"][0]["message"]["content"]
        if is_trimmed:
            content = "<strong>AI Summary (conent trimmed)</strong>" + content
        else:
            content = "<strong>AI Summary</strong>" + content
        return content
    else:
        print(f"Error summarizing content. {response.status_code}: {response.text}")
        return None


def extract_main_content(html_content, base_url):
    """Extract main content from HTML using readability-lxml and clean it with BeautifulSoup."""

    # TODO Check for special URLs and handle them accordingly - GitHub

    doc = Document(html_content)
    readable_content = doc.summary()

    # soup = BeautifulSoup(readable_content, 'lxml')
    # h1_tag = soup.find('h1')
    # if h1_tag:
    #     h1_tag.decompose()
    # for img_tag in soup.find_all('img'):
    #     img_tag.replace_with('[IMAGE]')
    # return str(soup)

    return readable_content


def parse_rss(rss_content):
    """Parse RSS feed and fetch the main content for each item."""
    root = ET.fromstring(rss_content)
    items = []
    for item in root.findall('.//item'):
        title = item.find('title').text
        pub_date = item.find('pubDate').text
        comments_link = item.find('comments').text
        link = item.find('link').text

        print(f"Fetching {link} => {title}")
        raw_content = fetch_content(link)

        if raw_content:
            content = extract_main_content(raw_content, link)
            ai_summary = ai_summarize(content)

            items.append({
                'title': title,
                'pub_date': pub_date,
                'link': link,
                'comments_link': comments_link,
                'ai_summary': ai_summary,
                'content': content,
            })
    return items


def create_epub(items):
    """Create an EPUB book from a list of items including navigation links."""
    title = f"Hacker News - {datetime.now().strftime('%B %d, %Y')}"
    output_filename = f"{title}.epub"

    book = epub.EpubBook()
    book.set_identifier('id123456')
    book.set_title(title)
    book.set_language('en')
    book.add_author('MakePub')

    book.spine = ['nav']
    toc = []
    chapters = []

    for i, item in enumerate(items, start=1):
        # Prepare navigation html
        navigation_html = '<div style="text-align:center; margin-top:20px;">'

        # Previous article link, if it's not the first article
        if i > 1:
            prev_file_name = f'chap_{i-1}.xhtml'
            navigation_html += f'<a href="{prev_file_name}"><< Previous</a> '

        navigation_html += " | "

        # Next article link, if it's not the last article
        if i < len(items):
            next_file_name = f'chap_{i+1}.xhtml'
            navigation_html += f'<a href="{next_file_name}">Next >></a>'

        # Other links
        navigation_html += '<br><a href="toc.xhtml">TOC</a> | '
        navigation_html += f'<a href="{item["link"]}">Original</a> | '
        navigation_html += f'<a href="{item["comments_link"]}">Comments</a>'

        navigation_html += '</div>'

        # Content with navigation
        content = f"<h1>{item['title']}</h1>"
        content += f"{navigation_html}"
        if item['ai_summary'] is not None:
            content += f"<p>{item['ai_summary']}</p>"
        # content += f"{item['content']}"

        # Creating chapter
        chapter = epub.EpubHtml(title=item['title'], file_name=f'chap_{i}.xhtml', lang='en')
        chapter.content = content
        book.add_item(chapter)

        chapters.append(chapter)
        book.spine.append(chapter)
        toc.append(epub.Link(chapter.file_name, item['title'], f'chap_{i}'))

    # Defining the TOC and spine
    book.toc = toc

    # Adding navigation files and toc.xhtml manually
    nav_doc = epub.EpubHtml(title='TOC', file_name='toc.xhtml', lang='en')
    toc_content = '<h1>Table of Contents</h1><ul>'
    for i, chapter in enumerate(chapters, start=1):
        toc_content += f'<li><a href="{chapter.file_name}">{chapter.title}</a></li>'
    toc_content += '</ul>'
    nav_doc.content = toc_content
    book.add_item(nav_doc)

    # Adding necessary navigation files
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(output_filename, book, {})

    print(f"EPUB generated: {output_filename}")


def main():

    # Hacker News
    url = "https://news.ycombinator.com/rss"
    rss_content = fetch_content(url)
    if rss_content:
        items = parse_rss(rss_content)
        create_epub(items)

    # RSS file


if __name__ == "__main__":
    main()
