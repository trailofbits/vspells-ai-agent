from typing import Literal, TypedDict
from pydantic import BaseModel


class FunctionModel(TypedDict):
    category: Literal["sink", "source", "parser", "nonparser", "maybeparser"]
    return_type: Literal["data", "nodata", "maybedata"]
    arguments: list[Literal["data", "nodata", "maybedata"]]
    is_stdlib: bool


class AnalysisResponse(FunctionModel):
    reasoning: str


def analyze_function(
    file_contents: str,
    context: str,
    function_name: str,
    no_args: int,
    file_path: str | None,
):
    return f"""Your task is to categorize a given function based on its role in parsing, handling, or processing data. You will receive file contents, context, a function name, and possible output categories. Analyze the information provided and categorize the function according to the given criteria.

First, review the following file contents:

<file_contents>

{file_contents}

</file_contents>

{f"The path to this file is `{file_path}`" if file_path else ""}

Now, consider this additional context that may be relevant to your analysis:

<context>

{context}

</context>

Your goal is to analyze and categorize a function based on the following definitions and categories:

1. Parser: Any function that takes arbitrary user input and produces structured output.
2. Source: Any function that produces arbitrary user input.
3. Sink: Any function that accepts potentially arbitrary user data and doesn't propagate it further.
4. Maybeparser: Any function that accepts potentially arbitrary user data, does not necessarily perform parsing itself, but may still propagate it further.
5. Nonparser: Any other kind of function that doesn't fit into the above categories.

Additionally, consider these value types:
- "data": Values subject to parsing.
- "nodata": Values not subject to parsing.
- "maybedata": Values that could contain either "data" or "nodata".

Important rules:
- A nonparser can only accept nodata arguments and must return nodata.
- A sink can only return nodata.
- Focus on the function's behavior rather than its name when categorizing.
- When considering taint tracking, only mark data as tainted if it will be subject to further parsing, not in a general sense.

Please conduct your analysis using the following steps:

1. List all relevant code snippets from the file_contents that pertain to the function being analyzed.
2. Summarize the function's overall purpose based on the given context and file contents.
3. Examine the function's behavior based on the given context and file contents.
4. Consider how the function interacts with other parts of the system.
5. Consider how well the function fits into each category (Parser, Source, Sink, Maybeparser, Nonparser).
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

Keep your analysis to about 3 paragraphs.

Here are some examples of functions and their categories, return and argument types:

    #
    # Parser data sources
    #

    # char * fgets(char * restrict str, int size, FILE * restrict stream);
    - function: fgets
      model:
          return_type: data
          arguments:
          - data    # char * restrict str
          - nodata  # int size
          - nodata  # FILE * restrict stream
          category: source

    # size_t fread(void * restrict buffer, size_t size, size_t count, FILE * restrict stream);
    - function: fread
      model:
          return_type: nodata
          arguments:
          - data    # void * restrict buffer
          - nodata  # size_t size
          - nodata  # size_t count
          - nodata  # FILE * restrict stream
          category: source

    # char * gets(char * str);
    - function: gets
      model:
          return_type: data
          arguments:
          - data    # char * str
          category: source

    # char * gets_s(char * str, rsize_t n);
    - function: gets_s
      model:
          return_type: data
          arguments:
          - data    # char * str
          - nodata  # rsize_t n
          category: source

    # int getchar(void);
    - function: getchar
      model:
          return_type: data
          arguments: []
          category: source

    # int scanf(const char * restrict format, ...);
    - function: scanf
      model:
          return_type: nodata
          arguments:
          - nodata  # const char * restrict format
          - data    # ...
          category: source

    #
    # Parser data sinks
    #

    # int printf(const char * restrict format, ...);
    - function: printf
      model:
          return_type: nodata
          arguments:
          - maybedata  # const char * restrict format
          - maybedata # ...
          category: sink

    # int fprintf(FILE * restrict stream, const char * restrict format, ...);
    - function: fprintf
      model:
          return_type: nodata
          arguments:
          - nodata  # FILE * restrict stream
          - maybedata # const char * restrict format
          - maybedata # ...
          category: sink

    # void perror(const char *s);
    - function: perror
      model:
          return_type: nodata
          arguments:
          - maybedata  # const char *s
          category: sink

    # void free(void * ptr);
    - function: free
      model:
          return_type: nodata
          arguments:
          - maybedata  # void * ptr
          category: sink

    # FILE * fopen(const char * restrict filename, const char * restrict mode);
    - function: fopen
      model:
          return_type: nodata
          arguments:
          - maybedata  # const char * restrict filename
          - maybedata  # const char * restrict mode
          category: sink

    #
    # Parser functions
    #

    # int isspace(int c);
    - function: isspace
      model:
          return_type: nodata
          arguments:
          - data  # int c
          category: parser

    # int isdigit(int c);
    - function: isdigit
      model:
          return_type: nodata
          arguments:
          - data  # int c
          category: parser

    #
    # Non-parser functions
    #

    # void exit(int status);
    - function: exit
      model:
          return_type: nodata
          arguments:
          - nodata  # int status
          category: nonparser

    # void * malloc(size_t size);
    - function: malloc
      model:
          return_type: nodata
          arguments:
          - nodata  # size_t size
          category: nonparser

    # void fclose(FILE * stream);
    - function: fclose
      model:
          return_type: nodata
          arguments:
          - nodata  # FILE * stream
          category: nonparser

Consider the function `{function_name}`, which takes {no_args} argument(s) as input.

Please answer the following questions about `{function_name}`:

- What is the reasoning that led you to your answers?
- What category does `{function_name}` belong to?
- What data type does `{function_name}` return?
- What data types are the {no_args} argument(s) passed to `{function_name}`?
- Is `{function_name}` part of the standard libraries of this system?

"""

class FeedbackResponse(BaseModel):
    feedback: str
    accept_analysis: bool

def provide_feedback(
    file_contents: str,
    context: str,
    function_name: str,
    no_args: int,
    file_path: str | None,
    response: AnalysisResponse,
):
    reasoning = response["reasoning"]
    model = FunctionModel(
        category=response["category"],
        return_type=response["return_type"],
        arguments=response["arguments"],
        is_stdlib=response["is_stdlib"],
    )
    import json
    return f"""Your task is to provide feedback on a machine's analysis of a specific function in a C source file.

Here is the content of the source file to be analyzed:

<file_contents>
{file_contents}
</file_contents>

The path to this file is:
<file_path>
{file_path}
</file_path>

Consider this additional context that may be relevant to your analysis:

<context>
{context}
</context>

The function being analyzed is:
<function_name>
{function_name}
</function_name>

The machine has categorized this function as follows:

<analysis>
{
    json.dumps(model, indent=2)
}
</analysis>

The machine has provided the following reasoning for its categorization:

<reasoning>
{reasoning}
</reasoning>

Your task is to evaluate the machine's analysis and provide feedback. Consider the following categories and definitions:

1. Parser: Any function that takes arbitrary user input and produces structured output.
2. Source: Any function that produces arbitrary user input.
3. Sink: Any function that accepts potentially arbitrary user data and doesn't propagate it further.
4. Maybeparser: Any function that accepts potentially arbitrary user data, does not necessarily perform parsing itself, but may still propagate it further.
5. Nonparser: Any other kind of function that doesn't fit into the above categories.

Additionally, consider these value types:
- "data": Values subject to parsing.
- "nodata": Values not subject to parsing.
- "maybedata": Values that could contain either "data" or "nodata".

Important rules:
- A nonparser can only accept nodata arguments and must return nodata.
- A sink can only return nodata.
- Focus on the function's behavior rather than its name when categorizing.
- When considering taint tracking, only mark data as tainted if it will be subject to further parsing, not in a general sense.
- Try to think of potential uses of the function that would contradict the provided analysis.
- If you believe the analysis is valid as is, state so explicitly.

In your analysis, please:
1. Evaluate the accuracy of the machine's categorization.
2. Assess the correctness of the machine's reasoning.
3. Consider any edge cases or potential misuses of the function that could affect its categorization.
4. Discuss the implications of this function's behavior for dataflow analysis and taint tracking.

Provide your feedback in well-structured, clear, professional language.

1. Summarize the function's behavior based on the provided code and context.
2. List out the key characteristics that support or contradict each category (Parser, Source, Sink, Maybeparser, Nonparser).
3. Analyze the function's arguments and return values in terms of the given value types (data, nodata, maybedata).
4. Consider potential edge cases or misuses that could affect the categorization.
5. Present examples that would contradict the decisions made by the machine, if applicable.

Your response should be a JSON object containing both:
- A "feedback" field with your feedback
- A "accept_analysis" field with a boolean telling whether you recognize the analysis as correct or not

Keep your feedback to around 3 paragraphs.
"""