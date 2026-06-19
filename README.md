# Gmail Job Tracker

This projects goal is to help track job application by sifting through your gmail inbox and extracting relevant information.

It aims to automate the process of tracking applications rather than using a 3rd party tool or manually tracking them. 

## How it works

This program uses a mix of regex patterns and AI (pydantic AI), a hybrid approach was chosen to balance accuracy, complexity, and cost. 

First, the program soley used regex patterns and functions to find each application by searching for words like "application", "job", "position", etc. in the email subject and body. Then, after some testing, it was found this regex approach was missing some emails. So, rather than listing every single possible word that could be used in an email subject or body, AI was used to help identify applications. 

Most significantly, using Pydantic AI allowed for the creation of an 'extraction_agent' that could be used to extract the company_name and status of each application. 

## Later on

I plan to include a filtering system prior to the loading, this is something I learned from my data engineering experience when you are pulling in large amounts of unsupervised data. Rather than pulling in 10k emails and then filtering them, I want to filter them as I pull them in to reduce the amount of data processed.

## Current trouble areas

I'm having a difficult time with the AI agent not properly extracting some of the company_names (only a handful of these are incorrect, where they are pulling in the 'do not reply' instead). 

But, most importantly, I'm having a difficult time with pulling in the job_title for each application. First, I tried a regex approach, then I tried using a seperate agent, and now I reverted to a hybrid approach where if the 'extraction_agent' sees the job_title in the Subject line, it'll extract it, otherwise it'll use the regex approach to find it in the body the email. 

