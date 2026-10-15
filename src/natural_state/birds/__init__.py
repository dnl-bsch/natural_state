"""Turn BirdNET predictions into bird observations, following Wood & Kahl (2024).

The steps are:

1. Convert BirdNET confidence scores back to the logit scale.
2. For each species, fit a logistic regression of "prediction is correct" on the logit score,
   using the clips that an ornithologist validated.
3. Solve the fitted curve for the target probability (default 0.99) to get a score threshold.
4. Every prediction at or above its species threshold becomes an observation.

References
----------
Wood, C. M. & Kahl, S. (2024). Guidelines for appropriate use of BirdNET scores and other
detector outputs. Journal of Ornithology. https://doi.org/10.1007/s10336-024-02144-5
"""
