# Security Policy

## Supported Versions

We currently support 4CAT's master branch only.

## Basic security

4CAT relies on credentials stored in the config.py file. This includes access to your database where all information is
stored as well as API keys for third-party services. Therefore anyone with access to this file will be able to access 
your database and use these keys. It is important to insure this file is protected.

This is also true of a Docker installation. Whoever can access your Docker container, can also access the config.py 
file.

## Reporting a Vulnerability

Please email reports about any security related issues you find to 4cat@oilab.eu. Your email will be acknowledged and 
you'll receive a more detailed response to your email indicating the next steps in handling your report. 

Please use a descriptive subject line for your report email. After the initial reply to your report, the security team 
will endeavor to keep you informed of the progress being made towards a fix and announcement.

In addition, please include the following information along with your report:

- Your name and affiliation (if any).
- A description of the technical details of the vulnerabilities. It is very important to let us know how we can 
  reproduce your findings.
- An explanation who can exploit this vulnerability, and what they gain when doing so -- write an attack scenario. 
- This will help us evaluate your report quickly, especially if the issue is complex.
- Whether this vulnerability public or known to third parties. If it is, please provide details.

If you believe that an existing (public) issue is security-related, please send an email to 4cat@oilab.eu. The email 
should include the issue ID and a short description of why it should be handled according to this security policy.

Once an issue is reported, we use the following disclosure process:

- When a report is received, we confirm the issue and determine its severity.
- If we know of specific third-party services or software based on 4CAT that require mitigation before publication, 
  those projects will be notified.
- An advisory is prepared (but not published) which details the problem and steps for mitigation.
- The vulnerability is fixed and potential workarounds are identified.
- Patch releases are published for all fixed released versions and the advisory is published.
