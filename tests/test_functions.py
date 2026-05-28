import pytest
from rv_pytools.functions import ordinal


# Basic ordinals
def test_ordinal_1():
    assert ordinal(1) == "1st"

def test_ordinal_2():
    assert ordinal(2) == "2nd"

def test_ordinal_3():
    assert ordinal(3) == "3rd"

def test_ordinal_4():
    assert ordinal(4) == "4th"

def test_ordinal_5():
    assert ordinal(5) == "5th"

def test_ordinal_10():
    assert ordinal(10) == "10th"

# Teen exceptions (11, 12, 13 always use "th")
def test_ordinal_11():
    assert ordinal(11) == "11th"

def test_ordinal_12():
    assert ordinal(12) == "12th"

def test_ordinal_13():
    assert ordinal(13) == "13th"

# Tens with st/nd/rd suffixes
def test_ordinal_21():
    assert ordinal(21) == "21st"

def test_ordinal_22():
    assert ordinal(22) == "22nd"

def test_ordinal_23():
    assert ordinal(23) == "23rd"

def test_ordinal_100():
    assert ordinal(100) == "100th"

# Hundreds with teen exceptions
def test_ordinal_111():
    assert ordinal(111) == "111th"

def test_ordinal_112():
    assert ordinal(112) == "112th"

def test_ordinal_113():
    assert ordinal(113) == "113th"

def test_ordinal_101():
    assert ordinal(101) == "101st"
