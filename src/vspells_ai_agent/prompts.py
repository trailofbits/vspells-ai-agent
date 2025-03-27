from pydantic import BaseModel, Field
from typing import Literal


class CategoryAgentResponse(BaseModel):
    reasoning: str = Field(
        description="The reasoning steps that made you decide on the final answer"
    )
    response: Literal["nonparser", "parser", "sink", "source"] = Field(
        description="The final answer on what category this function belongs to"
    )
    isStdlib: bool = Field(
        description="Whether or not this function is part of the standard libraries of this system"
    )


def function_category(file_contents: str, context: str, function_name: str):
    return f"""Your task is to categorize a given function based on its role in parsing, handling, or processing data. You will receive file contents, context, a function name, and possible output categories. Analyze the information provided and categorize the function according to the given criteria.

First, review the following file contents:

<file_contents>
{file_contents}
</file_contents>

Now, consider this additional context that may be relevant to your analysis:

<context>
{context}
</context>

Your goal is to analyze and categorize a function based on the following definitions and categories:

1. Parser: Any function that takes arbitrary user input and produces structured output.
2. Source: Any function that produces arbitrary user input.
3. Sink: Any function that accepts potentially arbitrary user data and doesn't propagate it further.
4. Nonparser: Any other kind of function that doesn't fit into the above categories.

Additionally, consider these value types:
- "data": Values subject to parsing.
- "nodata": Values not subject to parsing.
- "maybedata": Values that could contain either "data" or "nodata".

IMPORTANT: Focus on analyzing the function's behavior rather than its name. The name itself should not be the primary factor in your categorization.

Please conduct your analysis using the following steps:

1. List all relevant code snippets from the file_contents that pertain to the function being analyzed.
2. Summarize the function's overall purpose based on the given context and file contents.
3. Examine the function's behavior based on the given context and file contents.
4. Consider how the function interacts with other parts of the system.
5. Consider how well the function fits into each category (Parser, Source, Sink, Nonparser).
6. Evaluate how the function might handle input.
7. Assess how the function might handle output.
8. Determine which value type (data, nodata, maybedata) the function is likely to work with.
9. Consider edge cases and potential ambiguities.
10. Make a final determination on the most appropriate category.
11. State any assumptions made during the analysis.
12. Provide a confidence rating (0-100%) for your final categorization.

For each step of your analysis:

- Quote relevant parts of the file_contents and context that support your analysis.
- For steps 5 and 8, list arguments for and against each category or value type, provide a confidence level (0-100%) for each, and number each piece of evidence.
- Provide detailed reasoning for your conclusions.
- For step 9, explicitly state any edge cases or ambiguities you've identified.

Here's an example of how your response should be structured:

    1. Relevant code snippets:
    [List code snippets here]

    2. Function purpose summary:
    The function appears to...

    3. Function behavior examination:
    Relevant quote from file_contents: "..."
    Relevant quote from context: "..."
    The function appears to...

    [Steps 4-12 following the same structure]

What category does the function `{function_name}` belong to?

Your response should be a JSON object containing:
    - "reasoning" field containing a string describing your reasoning
    - "response" field containing one of "nonparser", "parser", "sink", "source"
    - "isStdlib" field containing a boolean whether or not this function is part of the standard libraries of this system
"""


class ReturnTypeAgentResponse(BaseModel):
    reasoning: str = Field(
        description="The reasoning steps that made you decide on the final answer"
    )
    response: Literal["data", "nodata", "maybedata"] = Field(
        description="The final answer on what type this function returns"
    )


def return_type(file_contents: str, context: str, function_name: str):
    return f"""Your task is to decide a given function's return type based on its role in parsing, handling, or processing data. You will receive file contents, context, a function name, and possible output categories. Analyze the information provided and categorize the function according to the given criteria.

First, review the following file contents:

<file_contents>
{file_contents}
</file_contents>

Now, consider this additional context that may be relevant to your analysis:

<context>
{context}
</context>

Your goal is to analyze and categorize a function based on the following definitions and categories:

1. Parser: Any function that takes arbitrary user input and produces structured output.
2. Source: Any function that produces arbitrary user input.
3. Sink: Any function that accepts potentially arbitrary user data and doesn't propagate it further.
4. Nonparser: Any other kind of function that doesn't fit into the above categories.

Additionally, consider these value types:
- "data": Values subject to parsing.
- "nodata": Values not subject to parsing.
- "maybedata": Values that could contain either "data" or "nodata".

IMPORTANT: Focus on analyzing the function's behavior rather than its name. The name itself should not be the primary factor in your categorization.

Please conduct your analysis using the following steps:

1. List all relevant code snippets from the file_contents that pertain to the function being analyzed.
2. Summarize the function's overall purpose based on the given context and file contents.
3. Examine the function's behavior based on the given context and file contents.
4. Consider how the function interacts with other parts of the system.
5. Consider how well the function fits into each category (Parser, Source, Sink, Nonparser).
6. Evaluate how the function might handle input.
7. Assess how the function might handle output.
8. Determine which value type (data, nodata, maybedata) the function is likely to work with.
9. Consider edge cases and potential ambiguities.
10. Make a final determination on the most appropriate category.
11. State any assumptions made during the analysis.
12. Provide a confidence rating (0-100%) for your final categorization.

For each step of your analysis:

- Quote relevant parts of the file_contents and context that support your analysis.
- For steps 5 and 8, list arguments for and against each category or value type, provide a confidence level (0-100%) for each, and number each piece of evidence.
- Provide detailed reasoning for your conclusions.
- For step 9, explicitly state any edge cases or ambiguities you've identified.

Here's an example of how your response should be structured:

    1. Relevant code snippets:
    [List code snippets here]

    2. Function purpose summary:
    The function appears to...

    3. Function behavior examination:
    Relevant quote from file_contents: "..."
    Relevant quote from context: "..."
    The function appears to...

    [Steps 4-12 following the same structure]

What type does the function `{function_name}` return?

Your response should be a JSON object containing:
    - "reasoning" field containing a string describing your reasoning
    - "response" field containing one of "data", "nodata", "maybedata"
"""


class ArgumentTypeAgentResponse(BaseModel):
    reasoning: str = Field(
        description="The reasoning steps that made you decide on the final answer"
    )
    response: Literal["data", "nodata", "maybedata"] = Field(
        description="The final answer on what type this argument is"
    )


def argument_type(file_contents: str, context: str, function_name: str, index: int):
    return f"""Your task is to decide a given function's argument types based on its role in parsing, handling, or processing data. You will receive file contents, context, a function name, and possible output categories. Analyze the information provided and categorize the function according to the given criteria.

First, review the following file contents:

<file_contents>
{file_contents}
</file_contents>

Now, consider this additional context that may be relevant to your analysis:

<context>
{context}
</context>

Your goal is to analyze and categorize a function based on the following definitions and categories:

1. Parser: Any function that takes arbitrary user input and produces structured output.
2. Source: Any function that produces arbitrary user input.
3. Sink: Any function that accepts potentially arbitrary user data and doesn't propagate it further.
4. Nonparser: Any other kind of function that doesn't fit into the above categories.

Additionally, consider these value types:
- "data": Values subject to parsing.
- "nodata": Values not subject to parsing.
- "maybedata": Values that could contain either "data" or "nodata".

IMPORTANT: Focus on analyzing the function's behavior rather than its name. The name itself should not be the primary factor in your categorization.

Please conduct your analysis using the following steps:

1. List all relevant code snippets from the file_contents that pertain to the function being analyzed.
2. Summarize the function's overall purpose based on the given context and file contents.
3. Examine the function's behavior based on the given context and file contents.
4. Consider how the function interacts with other parts of the system.
5. Consider how well the function fits into each category (Parser, Source, Sink, Nonparser).
6. Evaluate how the function might handle input.
7. Assess how the function might handle output.
8. Determine which value type (data, nodata, maybedata) the function is likely to work with.
9. Consider edge cases and potential ambiguities.
10. Make a final determination on the most appropriate category.
11. State any assumptions made during the analysis.
12. Provide a confidence rating (0-100%) for your final categorization.

For each step of your analysis:

- Quote relevant parts of the file_contents and context that support your analysis.
- For steps 5 and 8, list arguments for and against each category or value type, provide a confidence level (0-100%) for each, and number each piece of evidence.
- Provide detailed reasoning for your conclusions.
- For step 9, explicitly state any edge cases or ambiguities you've identified.

Here's an example of how your response should be structured:

    1. Relevant code snippets:
    [List code snippets here]

    2. Function purpose summary:
    The function appears to...

    3. Function behavior examination:
    Relevant quote from file_contents: "..."
    Relevant quote from context: "..."
    The function appears to...

    [Steps 4-12 following the same structure]

What is the type of argument #{index} of the function `{function_name}`?

Your response should be a JSON object containing:
    - "reasoning" field containing a string describing your reasoning
    - "response" field containing one of "data", "nodata", "maybedata"
"""
