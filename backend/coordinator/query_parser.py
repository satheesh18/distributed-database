"""
Query Parser - Simple SQL Query Parser

Parses SQL queries to determine:
- Query type (SELECT, INSERT, UPDATE, DELETE)
- Target tables
- Basic validation

This is a simplified parser for the project - not a full SQL parser.
"""

import re
from typing import Tuple, List


def parse_query(query: str) -> Tuple[str, List[str]]:
    """
    Parse a SQL query to determine its type and target tables.
    
    Args:
        query: SQL query string
        
    Returns:
        Tuple of (query_type, tables)
        - query_type: "SELECT", "INSERT", "UPDATE", "DELETE", or "UNKNOWN"
        - tables: List of table names referenced in the query
    """
    # Normalize query: strip whitespace and convert to uppercase for parsing
    normalized = query.strip().upper()
    
    # Determine query type
    if normalized.startswith("SELECT"):
        query_type = "SELECT"
    elif normalized.startswith("INSERT"):
        query_type = "INSERT"
    elif normalized.startswith("UPDATE"):
        query_type = "UPDATE"
    elif normalized.startswith("DELETE"):
        query_type = "DELETE"
    else:
        query_type = "UNKNOWN"
    
    # Extract table names (simplified approach)
    tables = extract_tables(query, query_type)
    
    return query_type, tables


def extract_tables(query: str, query_type: str) -> List[str]:
    """
    Extract table names from a SQL query.
    
    This is a simplified implementation that handles basic cases.
    
    Args:
        query: SQL query string
        query_type: Type of query (SELECT, INSERT, UPDATE, DELETE)
        
    Returns:
        List of table names
    """
    tables = []
    normalized = query.upper()
    
    try:
        if query_type == "SELECT":
            # Extract FROM clause
            match = re.search(r'FROM\s+(\w+)', normalized)
            if match:
                tables.append(match.group(1).lower())
        
        elif query_type == "INSERT":
            # Extract INTO clause
            match = re.search(r'INTO\s+(\w+)', normalized)
            if match:
                tables.append(match.group(1).lower())
        
        elif query_type == "UPDATE":
            # Extract table name after UPDATE
            match = re.search(r'UPDATE\s+(\w+)', normalized)
            if match:
                tables.append(match.group(1).lower())
        
        elif query_type == "DELETE":
            # Extract FROM clause
            match = re.search(r'FROM\s+(\w+)', normalized)
            if match:
                tables.append(match.group(1).lower())
    
    except Exception as e:
        print(f"Error extracting tables: {e}")
    
    return tables


def is_write_query(query_type: str) -> bool:
    """
    Determine if a query type is a write operation.
    
    Args:
        query_type: Type of query
        
    Returns:
        True if write operation, False otherwise
    """
    return query_type in ["INSERT", "UPDATE", "DELETE"]


def is_read_query(query_type: str) -> bool:
    """
    Determine if a query type is a read operation.
    
    Args:
        query_type: Type of query
        
    Returns:
        True if read operation, False otherwise
    """
    return query_type == "SELECT"
