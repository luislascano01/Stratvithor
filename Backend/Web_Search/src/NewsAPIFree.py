import requests

def main():
    # Define the endpoint and your API key.
    url = 'https://newsapi.org/v2/everything'
    api_key = '7075939595a1436da08761b3b64b795b'  # Replace with your actual API key

    # Set up parameters for the search query.
    params = {
        'q': 'Ukraine War',                # The search query; change to your desired topic.
        'from': '2025-03-01',           # Start date (YYYY-MM-DD)
        'sortBy': 'publishedAt',       # Sort articles by published date.
        'language': 'en',              # Filter for English articles.
        'pageSize': 20,                # Number of articles per page.
        'page': 1,                     # Retrieve the first page.
        'apiKey': api_key              # Your API key for News API.
    }

    # Make the GET request to News API.
    response = requests.get(url, params=params)

    # Check if the request was successful.
    if response.status_code == 200:
        data = response.json()
        print("Total Results:", data.get("totalResults"))
        print("=" * 40)
        for article in data.get("articles", []):
            print("Title:", article.get("title"))
            print("Description:", article.get("description"))
            print("URL:", article.get("url"))
            print("Date:", article.get("publishedAt"))
            print("-" * 40)
    else:
        print("Error:", response.status_code, response.text)

if __name__ == "__main__":
    main()