import psycopg2
from dotenv import load_dotenv
import os
from datetime import datetime
from psycopg2.extras import RealDictCursor
from db_connection import get_bonded_arena_tokens
from dexscreener_api import get_token_market_data

load_dotenv()

class MarketDataUpdater:
    def __init__(self):
        self.conn = None
        self.cur = None
        self._connect()
    
    def _connect(self):
        """Establish database connection"""
        try:
            self.conn = psycopg2.connect(
                host=os.getenv('DB_HOST'),
                port=os.getenv('DB_PORT'),
                dbname=os.getenv('DB_NAME'),
                user=os.getenv('DB_USER'),
                password=os.getenv('DB_PASSWORD')
            )
            self.cur = self.conn.cursor()
        except Exception as e:
            print(f"Database connection error: {str(e)}")
            raise
    
    def _get_bonded_tokens(self):
        """Get list of bonded token addresses"""
        try:
            bonded_tokens_df = get_bonded_arena_tokens()
            if bonded_tokens_df is None or bonded_tokens_df.empty:
                return []
            return bonded_tokens_df['token_address'].tolist()
        except:
            return []
    
    def _get_market_data(self, token_addresses):
        """Fetch market data from API"""
        try:
            return get_token_market_data(token_addresses, chain_id="avalanche") or {}
        except:
            return {}
    
    def _update_database(self, market_data):
        """Update database with market data"""
        try:
            for address, data in market_data.items():
                try:
                    # Extract data
                    token_name = data.get('name', 'Unknown')
                    token_symbol = data.get('symbol', 'Unknown')
                    market_cap = int(data.get('market_cap')) if data.get('market_cap') is not None else None
                    price_usd = data.get('price_usd')
                    volume_24h = data.get('volume_24h')
                    liquidity_usd = data.get('liquidity_usd')
                    website = data.get('website')
                    current_time = datetime.now()
                    
                    # Check if record exists
                    self.cur.execute("SELECT token_address FROM arena_market_data WHERE token_address = %s", (address,))
                    
                    if self.cur.fetchone():
                        # Update existing
                        self.cur.execute("""
                            UPDATE arena_market_data 
                            SET token_name = %s, token_symbol = %s, market_cap = %s,
                                price_usd = %s, volume_24h = %s, liquidity_usd = %s,
                                website = %s, last_updated = %s
                            WHERE token_address = %s
                        """, (token_name, token_symbol, market_cap, price_usd, 
                             volume_24h, liquidity_usd, website, current_time, address))
                    else:
                        # Insert new
                        self.cur.execute("""
                            INSERT INTO arena_market_data (
                                token_address, token_name, token_symbol, market_cap,
                                price_usd, volume_24h, liquidity_usd, website, last_updated
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (address, token_name, token_symbol, market_cap,
                             price_usd, volume_24h, liquidity_usd, website, current_time))
                except:
                    continue
            
            self.conn.commit()
        except:
            pass
    
    def update_market_data(self):
        """Main update process"""
        token_addresses = self._get_bonded_tokens()
        if not token_addresses:
            return
            
        market_data = self._get_market_data(token_addresses)
        if not market_data:
            return
            
        self._update_database(market_data)

if __name__ == "__main__":
    updater = MarketDataUpdater()
    updater.update_market_data()