from core.dashboard import app

if __name__ == "__main__":
    print("=" * 50)
    print("  RFP Dashboard")
    print("  Open: http://localhost:5000")
    print("  Press Ctrl+C to stop")
    print("=" * 50)
    app.run(debug=False, port=5000, host="127.0.0.1")
