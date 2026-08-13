import os


# Test runs must be deterministic and must never consume a developer's local API quota.
os.environ["MATH_AI_DEEPSEEK_API_KEY"] = ""
os.environ["MATH_AI_LESSON_PLAN_PROVIDER"] = "local"
os.environ["MATH_AI_QUESTION_VARIANT_PROVIDER"] = "local"
os.environ["MATH_AI_SOLUTION_PROVIDER"] = "local"
