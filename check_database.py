from setup_graph_database import get_graph_db_connection
from sqlalchemy import text

def check_database_status():
    """Check what data has been uploaded to the database"""
    engine = get_graph_db_connection()
    
    with engine.connect() as conn:
        # Check token deployments
        result = conn.execute(text('SELECT COUNT(*) as count FROM token_deployments'))
        token_count = result.fetchone()[0]
        print(f"🪙 Token deployments: {token_count}")
        
        # Check bonding events
        result = conn.execute(text('SELECT COUNT(*) as count FROM bonding_events'))
        event_count = result.fetchone()[0]
        print(f"💰 Bonding events: {event_count}")
        
        # Check user activities
        result = conn.execute(text('SELECT COUNT(*) as count FROM user_activity'))
        user_count = result.fetchone()[0]
        print(f"👥 User activities: {user_count}")
        
        # Sample token data
        result = conn.execute(text('SELECT name, symbol, total_trades, total_avax_volume FROM token_deployments WHERE total_trades > 0 LIMIT 5'))
        print(f"\n📊 Sample tokens with trading activity:")
        for row in result:
            print(f"  • {row[0]} ({row[1]}) - {row[2]} trades, {row[3]:.4f} AVAX volume")
        
        # Sample bonding events
        result = conn.execute(text('SELECT token_address, trade_type, avax_amount, user_address FROM bonding_events LIMIT 5'))
        print(f"\n💱 Sample bonding events:")
        for row in result:
            user_addr = row[3].hex()[:8] + "..." if row[3] else "N/A"
            print(f"  • {row[1]} {row[2]:.4f} AVAX on {row[0]} by {user_addr}")

if __name__ == "__main__":
    check_database_status() 