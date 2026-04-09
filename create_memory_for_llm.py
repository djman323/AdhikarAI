from rag_engine import ConstitutionRAGEngine


def main() -> None:
    engine = ConstitutionRAGEngine()
    engine.ensure_index()
    print("Document index is ready at vectorstore/.")


if __name__ == "__main__":
    main()