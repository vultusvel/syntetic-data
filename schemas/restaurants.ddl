-- Restaurants sample schema
CREATE TABLE restaurants (
    restaurant_id  SERIAL PRIMARY KEY,
    name           VARCHAR(120) NOT NULL,
    city           VARCHAR(80) NOT NULL,
    cuisine        VARCHAR(50),
    rating         NUMERIC(2,1),
    opened_on      DATE
);

CREATE TABLE customers (
    customer_id  SERIAL PRIMARY KEY,
    full_name    VARCHAR(100) NOT NULL,
    email        VARCHAR(120) UNIQUE,
    phone        VARCHAR(20),
    signup_date  DATE NOT NULL
);

CREATE TABLE menu_items (
    item_id        SERIAL PRIMARY KEY,
    restaurant_id  INTEGER NOT NULL REFERENCES restaurants(restaurant_id),
    item_name      VARCHAR(100) NOT NULL,
    category       VARCHAR(50),
    price          NUMERIC(6,2) NOT NULL
);

CREATE TABLE orders (
    order_id       SERIAL PRIMARY KEY,
    restaurant_id  INTEGER NOT NULL REFERENCES restaurants(restaurant_id),
    customer_id    INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date     TIMESTAMP NOT NULL,
    total_amount   NUMERIC(8,2) NOT NULL,
    status         VARCHAR(20) NOT NULL DEFAULT 'completed'
);

CREATE TABLE order_items (
    order_item_id  SERIAL PRIMARY KEY,
    order_id       INTEGER NOT NULL REFERENCES orders(order_id),
    item_id        INTEGER NOT NULL REFERENCES menu_items(item_id),
    quantity       INTEGER NOT NULL DEFAULT 1
);
