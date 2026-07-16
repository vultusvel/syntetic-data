-- Company / Employee sample schema
CREATE TABLE departments (
    department_id  SERIAL PRIMARY KEY,
    name           VARCHAR(80) NOT NULL,
    location       VARCHAR(80)
);

CREATE TABLE employees (
    employee_id    SERIAL PRIMARY KEY,
    first_name     VARCHAR(50) NOT NULL,
    last_name      VARCHAR(50) NOT NULL,
    email          VARCHAR(120) NOT NULL UNIQUE,
    hire_date      DATE NOT NULL,
    salary         NUMERIC(10,2) NOT NULL,
    department_id  INTEGER NOT NULL REFERENCES departments(department_id),
    manager_id     INTEGER REFERENCES employees(employee_id)
);

CREATE TABLE projects (
    project_id     SERIAL PRIMARY KEY,
    name           VARCHAR(120) NOT NULL,
    department_id  INTEGER NOT NULL REFERENCES departments(department_id),
    start_date     DATE NOT NULL,
    end_date       DATE,
    budget         NUMERIC(12,2)
);

CREATE TABLE assignments (
    assignment_id  SERIAL PRIMARY KEY,
    employee_id    INTEGER NOT NULL REFERENCES employees(employee_id),
    project_id     INTEGER NOT NULL REFERENCES projects(project_id),
    role           VARCHAR(50),
    allocation_pct INTEGER NOT NULL DEFAULT 100
);
