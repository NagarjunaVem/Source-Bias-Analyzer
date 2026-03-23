from app.input.loader import load_text
from app.analysis.bias_detector import analyze_bias


def main():
    article = load_text()

    print("\nAnalyzing article...\n")

    result = analyze_bias(article)

    print("\n=== RESULT ===\n")
    print(result)


if __name__ == "__main__":
    main()