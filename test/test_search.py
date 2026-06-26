from src.tools.web_search import web_search
from src.tools.crawl import crawl_tool



if __name__ == "__main__":
    from src.agent.types import State

    # Example usage of the web_search tool
    # state = State(messages=[{"content": "What is the latest in AI research?"}])

    # test_url = "http://www.baidu.com/link?url=iIb1GAB_XSvebiURUTdA7uFBpmAY-dCCiu7klqYeHYRAtPLJ3vpu2Ay7ItwNEokvq51KXEiHmUDu93nMripf60mejL75YCUrNLO89DRwcLA_dzBQLLDwyKb_NbJNmp8AhC-tkD3sahOUHuHIAUNMre_vYBi7C5Ei_gb8xSnUqIoajJuhKusIZX7I-OLncGt5dd-V4kk3y96D2G9nN_AbSkBIk2C1aiGidCR0uohk-xz-qMveYYYJEWgz5K5S9mv1_HnrMFresK_cuC6sVCvlwa&wd=&eqid=a665f7370015f3680000000569159929"
    # print(crawl_tool.invoke(test_url))

    searched_content = web_search.invoke("should school uniforms be mandatory IELTS high-scoring essay sample")
    print(searched_content)