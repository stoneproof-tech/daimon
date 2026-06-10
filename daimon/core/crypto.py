# -*- coding: utf-8 -*-
"""Primitive crittografiche e di serializzazione di DAIMON.

- Serializzazione canonica deterministica (per hashing e firme).
- Wallet umani: ECDSA secp256k1. (I daimon NON hanno chiavi umane.)
- Costruzione e verifica delle transazioni firmate, con nonce per account.
"""

import json
import hashlib

from ecdsa import SigningKey, VerifyingKey, SECP256k1, BadSignatureError

from ..config import ConsensusError


def canonical(obj) -> str:
    """Serializzazione canonica e stabile (chiavi ordinate, niente spazi)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class Wallet:
    """Account umano con chiave ECDSA secp256k1. L'indirizzo deriva dalla chiave."""

    def __init__(self, sk: SigningKey | None = None):
        self.sk = sk or SigningKey.generate(curve=SECP256k1)
        self.vk = self.sk.get_verifying_key()
        self.pubkey = self.vk.to_string().hex()
        self.address = "usr_" + sha("pk:" + self.pubkey)[:24]

    def sign(self, msg: str) -> str:
        return self.sk.sign(msg.encode("utf-8")).hex()

    @property
    def secret_hex(self) -> str:
        return self.sk.to_string().hex()

    @classmethod
    def from_secret_hex(cls, secret_hex: str) -> "Wallet":
        return cls(SigningKey.from_string(bytes.fromhex(secret_hex), curve=SECP256k1))

    def save(self, path: str) -> None:
        """Salva la chiave su file (mai versionare: vedi .gitignore *.wallet/keys/)."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"address": self.address, "secret": self.secret_hex}, f)

    @classmethod
    def load(cls, path: str) -> "Wallet":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_secret_hex(data["secret"])


def address_from_pubkey(pubkey_hex: str) -> str:
    return "usr_" + sha("pk:" + pubkey_hex)[:24]


def tx_signing_payload(tx: dict) -> str:
    """Corpo firmabile della transazione (esclude la firma)."""
    body = {k: tx[k] for k in ("type", "from", "nonce", "payload", "pubkey")}
    return canonical(body)


def make_tx(wallet: Wallet, ttype: str, payload: dict, nonce: int) -> dict:
    tx = {
        "type": ttype,
        "from": wallet.address,
        "nonce": nonce,
        "payload": payload,
        "pubkey": wallet.pubkey,
    }
    tx["sig"] = wallet.sign(tx_signing_payload(tx))
    return tx


def verify_tx_signature(tx: dict) -> None:
    """Verifica firma ECDSA e coerenza indirizzo↔chiave. Solleva ConsensusError."""
    try:
        vk = VerifyingKey.from_string(bytes.fromhex(tx["pubkey"]), curve=SECP256k1)
        vk.verify(bytes.fromhex(tx["sig"]), tx_signing_payload(tx).encode("utf-8"))
    except (BadSignatureError, ValueError, KeyError) as exc:
        raise ConsensusError(f"firma non valida: {exc}")
    if tx["from"] != address_from_pubkey(tx["pubkey"]):
        raise ConsensusError("indirizzo mittente incoerente con la chiave pubblica")
