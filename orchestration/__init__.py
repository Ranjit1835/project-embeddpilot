"""V2 orchestration: chains generation and validation.

This package sits ABOVE both generation/ and validator/ precisely so neither has
to import the other. The contamination guard (generator is never the judge)
forbids generation/ importing validator/; an orchestrator that must call both
therefore cannot live in generation/, and lives here instead.
"""
