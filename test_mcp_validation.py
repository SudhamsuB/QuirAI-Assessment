from pydantic import ValidationError
import pytest
pytest.importorskip("mcp", reason="Official MCP SDK must be installed for Task 1 tests")
from mcp_server import CustomerInput, RefundInput

@pytest.mark.parametrize('value', ['CUST-1234', 'cust-12345', 'CUST-123456', 'CUST-ABCDE', 'CUST-12345x', 12345])
def test_reject_customer_id(value):
    with pytest.raises(ValidationError):
        CustomerInput.model_validate({'customer_id': value})

def test_reject_extra():
    with pytest.raises(ValidationError):
        CustomerInput.model_validate({'customer_id': 'CUST-00001', 'is_admin': True})

@pytest.mark.parametrize('amount,reason', [(0, 'perfectly valid'), (-1, 'perfectly valid'), (float('nan'), 'perfectly valid'), (5, 'short'), (3.0, 'short'), (3.0, '          '), ('4.5', 'Valid reason text')])
def test_refund_errors(amount, reason):
    with pytest.raises(ValidationError):
        RefundInput.model_validate({'customer_id': 'CUST-00001', 'amount': amount, 'reason': reason})

def test_valid_refund():
    obj = RefundInput.model_validate({'customer_id': 'CUST-00001', 'amount': 5.5, 'reason': 'Duplicate charge'})
    assert obj.amount == 5.5
