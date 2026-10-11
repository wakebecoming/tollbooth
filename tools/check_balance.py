import json
from web3 import Web3

w3 = Web3(Web3.HTTPProvider("https://sepolia.base.org", request_kwargs={"timeout": 20}))
usdc = w3.eth.contract(
    address="0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    abi=[{"constant": True, "inputs": [{"name": "_owner", "type": "address"}],
          "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}],
          "type": "function"}],
)
buyer = json.load(open("wallets/test-buyer.json"))["address"]
bal = usdc.functions.balanceOf(buyer).call()
print(f"buyer {buyer} USDC balance: {bal / 1e6}")
