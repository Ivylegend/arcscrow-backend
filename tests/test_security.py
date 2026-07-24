from app.core.security import hash_password, siwe_message, verify_password


def test_password_hash_uses_argon2_and_verifies():
    encoded = hash_password("correct-horse-battery-staple")
    assert encoded.startswith("$argon2")
    assert verify_password(encoded, "correct-horse-battery-staple")
    assert not verify_password(encoded, "incorrect")


def test_siwe_message_binds_chain_domain_and_nonce():
    message = siwe_message(
        domain="app.arcscrow.com",
        address="0x0000000000000000000000000000000000000001",
        nonce="single-use-nonce",
        chain_id=5_042_002,
    )
    assert "app.arcscrow.com" in message
    assert "Chain ID: 5042002" in message
    assert "Nonce: single-use-nonce" in message
