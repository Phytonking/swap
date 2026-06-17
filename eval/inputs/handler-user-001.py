def display_name(user):
    """Render 'First Last' for the profile header."""
    return user.profile.first_name + " " + user.profile.last_name
