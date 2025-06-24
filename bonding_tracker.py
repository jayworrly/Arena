import psycopg2
from web3 import Web3
from datetime import datetime
from dotenv import load_dotenv
import time
import os
import logging
from multiprocessing import Pool

# Load environment variables
load_dotenv()

print("Starting Bonding Tracker...")

# Configuration
ARENA_FACTORY = Web3.to_checksum_address('0xF16784dcAf838a3e16bEF7711a62D12413c39BD1')
WAVAX_ADDRESS = Web3.to_checksum_address('0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7')

# ABIs
FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "tokenA", "type": "address"},
            {"internalType": "address", "name": "tokenB", "type": "address"}
        ],
        "name": "getPair",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "token0", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "token1", "type": "address"},
            {"indexed": False, "internalType": "address", "name": "pair", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "", "type": "uint256"}
        ],
        "name": "PairCreated",
        "type": "event"
    }
]

TOKEN_ABI = [
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"}
]

class BondingTracker:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider('https://api.avax.network/ext/bc/C/rpc'))
        self.factory_contract = self.w3.eth.contract(address=ARENA_FACTORY, abi=FACTORY_ABI)
        
    def _get_db_connection(self):
        """Get database connection"""
        try:
            return psycopg2.connect(
                dbname=os.getenv('DB_NAME'),
                user=os.getenv('DB_USER'),
                password=os.getenv('DB_PASSWORD'),
                host=os.getenv('DB_HOST'),
                port=os.getenv('DB_PORT')
            )
        except Exception as e:
            logging.error(f"Database connection error: {str(e)}")
            return None

    def _create_bonding_progress_table(self):
        """Create bonding_progress table if it doesn't exist"""
        conn = self._get_db_connection()
        if not conn:
            return False
            
        with conn.cursor() as cur:
            try:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS bonding_progress (
                        id SERIAL PRIMARY KEY,
                        last_block_scanned BIGINT NOT NULL,
                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
                return True
            except Exception as e:
                print(f"Error creating bonding_progress table: {str(e)}")
                return False
            finally:
                conn.close()

    def _get_latest_deployment_block(self):
        """Get the latest block number from token_deployments table"""
        conn = self._get_db_connection()
        if not conn:
            return None
            
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT MAX(block_number) FROM token_deployments")
                latest_block = cur.fetchone()[0]
                return latest_block
            except Exception as e:
                print(f"Error getting latest deployment block: {str(e)}")
                return None
            finally:
                conn.close()

    def _manage_bonding_progress(self, block_number=None):
        """Get or update last processed block for bonding tracking"""
        # Ensure bonding_progress table exists
        if not self._create_bonding_progress_table():
            return None

        conn = self._get_db_connection()
        if not conn:
            return None
            
        with conn.cursor() as cur:
            try:
                if block_number is None:  # Get last block
                    cur.execute("SELECT last_block_scanned FROM bonding_progress ORDER BY id DESC LIMIT 1")
                    result = cur.fetchone()
                    if not result:
                        # Get the latest block from token_deployments table
                        latest_block = self._get_latest_deployment_block()
                        if latest_block:
                            cur.execute("INSERT INTO bonding_progress (last_block_scanned) VALUES (%s)", (latest_block,))
                            conn.commit()
                            return latest_block
                        else:
                            print("No token deployments found in database")
                            return None
                    return result[0]
                else:  # Update last block
                    cur.execute("""
                        INSERT INTO bonding_progress (last_block_scanned) VALUES (%s)
                        ON CONFLICT (id) DO UPDATE
                        SET last_block_scanned = %s, last_updated = CURRENT_TIMESTAMP
                    """, (block_number, block_number))
                    conn.commit()
                    return True
            except Exception as e:
                print(f"Error managing bonding progress: {str(e)}")
                return None
            finally:
                conn.close()

    def scan_for_bonding_events(self, batch_size=2000):
        """Scan for PairCreated events and update bonding status"""
        try:
            # Get the last processed block
            last_processed_block = self._manage_bonding_progress()
            if not last_processed_block:
                print("Could not determine last processed block")
                return False

            current_block = self.w3.eth.block_number
            print(f"Scanning from block {last_processed_block} to {current_block} for bonding events...")

            conn = self._get_db_connection()
            if not conn:
                return False

            bonded_count = 0
            processed_blocks = last_processed_block

            # Process in batches
            for start_block in range(last_processed_block + 1, current_block + 1, batch_size):
                end_block = min(start_block + batch_size - 1, current_block)
                print(f"Processing blocks {start_block} to {end_block}...")

                try:
                    # Get PairCreated events
                    pair_events = self.factory_contract.events.PairCreated.get_logs(
                        fromBlock=start_block,
                        toBlock=end_block
                    )

                    print(f"Found {len(pair_events)} PairCreated events in this batch")

                    with conn.cursor() as cur:
                        for event in pair_events:
                            token0 = event['args']['token0']
                            token1 = event['args']['token1']
                            pair_address = event['args']['pair']
                            block_number = event['blockNumber']
                            
                            # Check if either token is WAVAX (indicating a bonding event)
                            bonded_token = None
                            if token0.lower() == WAVAX_ADDRESS.lower():
                                bonded_token = token1
                            elif token1.lower() == WAVAX_ADDRESS.lower():
                                bonded_token = token0
                            
                            if bonded_token:
                                # Check if this token exists in our database
                                cur.execute("""
                                    SELECT token_address FROM token_deployments 
                                    WHERE token_address = %s
                                """, (bonded_token,))
                                
                                if cur.fetchone():
                                    # Update the token as bonded
                                    try:
                                        block = self.w3.eth.get_block(block_number)
                                        bonded_at = datetime.fromtimestamp(block['timestamp'])
                                        
                                        cur.execute("""
                                            UPDATE token_deployments
                                            SET lp_deployed = TRUE, pair_address = %s, bonded_at = %s,
                                                bonded_block_number = %s
                                            WHERE token_address = %s
                                        """, (pair_address, bonded_at, block_number, bonded_token))
                                        
                                        print(f"Found bonded token: {bonded_token} with pair: {pair_address}")
                                        bonded_count += 1
                                    except Exception as e:
                                        print(f"Error updating bonded token {bonded_token}: {str(e)}")
                                        # Still count it even if update fails
                                        bonded_count += 1
                    
                    conn.commit()
                    processed_blocks = end_block
                    
                    # Update progress after each batch
                    self._manage_bonding_progress(processed_blocks)
                    
                    # Small delay to avoid overwhelming the RPC
                    time.sleep(0.1)
                    
                except Exception as e:
                    print(f"Error processing batch {start_block}-{end_block}: {str(e)}")
                    continue

            conn.close()
            print(f"Bonding scan completed: {bonded_count} newly bonded tokens found")
            print(f"Processed up to block {processed_blocks}")
            return True
            
        except Exception as e:
            print(f"Error in scan_for_bonding_events: {str(e)}")
            return False

    def check_unbonded_tokens(self, batch_size=100):
        """Check tokens starting from the last processed block"""
        conn = self._get_db_connection()
        if not conn:
            return
            
        try:
            with conn.cursor() as cur:
                # Get the highest block number from our database (most recent token deployment)
                cur.execute("SELECT MAX(block_number) FROM token_deployments")
                max_block = cur.fetchone()[0]
                if not max_block:
                    print("No tokens found in database")
                    return
                
                # Get count of all tokens in database
                cur.execute("SELECT COUNT(*) FROM token_deployments")
                total_tokens = cur.fetchone()[0]
                
                print(f"Checking {total_tokens} tokens starting from highest block {max_block} (working backwards)...")
                
                bonded_count = 0
                processed_count = 0
                
                # Process in batches, starting from the most recent
                offset = 0
                while offset < total_tokens:
                    cur.execute("""
                        SELECT token_address, block_number
                        FROM token_deployments
                        ORDER BY block_number DESC
                        LIMIT %s OFFSET %s
                    """, (batch_size, offset))
                    
                    tokens = cur.fetchall()
                    if not tokens:
                        break
                    
                    print(f"Processing batch {offset // batch_size + 1}: tokens {offset + 1} to {offset + len(tokens)} (blocks {tokens[-1][1]} to {tokens[0][1]})")
                    
                    for token_address, deployment_block in tokens:
                        try:
                            # Check if pair exists
                            pair_address = self.factory_contract.functions.getPair(token_address, WAVAX_ADDRESS).call()
                            
                            if pair_address != '0x0000000000000000000000000000000000000000':
                                # Token is bonded - update database
                                try:
                                    cur.execute("""
                                        UPDATE token_deployments
                                        SET lp_deployed = TRUE, pair_address = %s
                                        WHERE token_address = %s
                                    """, (pair_address, token_address))
                                    conn.commit()
                                    print(f"Found bonded token: {token_address} (block {deployment_block}) with pair: {pair_address}")
                                    bonded_count += 1
                                except Exception as e:
                                    print(f"Error updating bonded token {token_address}: {str(e)}")
                                    bonded_count += 1  # Still count it
                            
                            processed_count += 1
                            
                            # Rate limiting - small delay every 10 checks
                            if processed_count % 10 == 0:
                                time.sleep(0.1)
                            
                        except Exception as e:
                            print(f"Error checking token {token_address}: {str(e)}")
                            continue
                    
                    offset += batch_size
                    
                    # Progress update every batch
                    print(f"Progress: {processed_count}/{total_tokens} tokens checked, {bonded_count} bonded tokens found")
                
                print(f"Individual check completed: {bonded_count} bonded tokens found out of {processed_count} total tokens")
                
        except Exception as e:
            print(f"Error in check_unbonded_tokens: {str(e)}")
        finally:
            conn.close()

    def run(self):
        """Main execution method"""
        print("Starting bonding tracker...")
        
        # First, scan for new bonding events from where we left off
        if self.scan_for_bonding_events():
            print("Event scanning completed successfully")
        else:
            print("Event scanning failed")
        
        # Then check some unbonded tokens individually
        self.check_unbonded_tokens()
        
        print("Bonding tracker completed")

def main():
    tracker = BondingTracker()
    tracker.run()

if __name__ == "__main__":
    main()