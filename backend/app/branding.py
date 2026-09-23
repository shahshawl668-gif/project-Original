"""
What the product is called, on the server side.

The name reaches users from here in two places: the header row of every Excel
export, and the organization created for the built-in system account on a fresh
installation. Renaming it in one of those and not the other is how a product
ends up called two things.

Changing ``PRODUCT_NAME`` renames future exports immediately. It does not rename
an organization already stored — that row was written once, at install time, and
renaming rows behind someone's back is not what a constant should do.
"""

PRODUCT_NAME = "PayrollCheck"

#: Header row on generated workbooks.
REPORT_HEADING = f"{PRODUCT_NAME} report"
