# Partner Portal

Welcome to Partner Portal, a web application designed to connect users with various types of business partners based on their needs.

## Features

Onboarding: Describe what your organization needs and what it can offer.

Matching: Partners are ranked against your onboarding profile, with a score and
the reasons behind it shown on each card.

Filter Partners: Filter by organization type, location, and available resources.

Search: Search the current results by name, type, or expertise.

Pagination: Navigate through the partner list nine at a time.

Add Partner: Add a new partner record to the directory.

Partner Details: Click any card for full details, including contact information.

Request a Demo: Contact form on the landing page for organizations that want in.

## Technologies Used

Frontend: HTML, CSS, JavaScript (ES6+), Fetch API

Backend: Python (Flask), MySQL Database

Additional Tools: bcrypt for password hashing, CORS for cross-origin resource sharing


## Setup Instructions

Clone the repository

Install dependencies:

Backend (Python/Flask):
```bash
pip install -r requirements.txt
```
Frontend (JavaScript/HTML/CSS): No additional setup required.

Configuration:

Copy `.env.example` to `.env` and fill in your database credentials. The app
reads all secrets from there and will refuse to start if `DB_PASSWORD` is unset.
Never commit `.env`.

Database Setup:

Ensure MySQL server is installed and running, then create the database and
tables. `schema.sql` is the single source of truth for the schema; `seed.sql`
adds a dozen fictional partners so the search page has something to show.

```bash
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS partnerportaldb"
mysql -u root -p partnerportaldb < schema.sql
mysql -u root -p partnerportaldb < seed.sql
```

Run the Application:

Start the Flask backend server:

```bash
python app.py
```

Serve the frontend from the project root (opening the HTML files directly with
`file://` will break the API calls):

```bash
python -m http.server 8000
```

Then visit http://localhost:8000/index.html

## Usage

Start at `onboarding.html` and describe your organization. Your profile is saved
to the database and kept in `localStorage`, which is what the search page ranks
partners against — without it you get an unranked list.

On `ppsearch.html`, use the search box to narrow the current results, "Filters"
to query the server by type, location, or resources, and "Add Partner" to add a
record. Click any card to see full details and contact information.

## Known limitations

Onboarding profiles are not yet linked to user accounts, so an organization that
completes onboarding does not appear in anyone else's search results. Merging
`users`, `partners`, and `onboarding_profiles` into a single organizations model
is the next piece of work. Sessions are also not implemented — login stores a
name in `localStorage` and no endpoint requires authentication.

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

Please make sure to update tests as appropriate.

## License

[MIT](https://choosealicense.com/licenses/mit/)