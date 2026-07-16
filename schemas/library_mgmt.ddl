-- Library Management sample schema
CREATE TABLE authors (
    author_id   SERIAL PRIMARY KEY,
    first_name  VARCHAR(50) NOT NULL,
    last_name   VARCHAR(50) NOT NULL,
    birth_date  DATE,
    country     VARCHAR(50)
);

CREATE TABLE members (
    member_id    SERIAL PRIMARY KEY,
    full_name    VARCHAR(100) NOT NULL,
    email        VARCHAR(120) NOT NULL UNIQUE,
    join_date    DATE NOT NULL,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE books (
    book_id         SERIAL PRIMARY KEY,
    title           VARCHAR(200) NOT NULL,
    author_id       INTEGER NOT NULL REFERENCES authors(author_id),
    genre           VARCHAR(50),
    published_year  INTEGER,
    total_copies    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE loans (
    loan_id     SERIAL PRIMARY KEY,
    book_id     INTEGER NOT NULL REFERENCES books(book_id),
    member_id   INTEGER NOT NULL REFERENCES members(member_id),
    loan_date   DATE NOT NULL,
    due_date    DATE NOT NULL,
    return_date DATE
);
