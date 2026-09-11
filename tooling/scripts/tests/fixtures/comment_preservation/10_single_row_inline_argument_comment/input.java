public class T
{
    void t()
    {
        outer.call(inner(alphaValue, /* note */ betaValue), tag);
        other.call(first, /* why */ second);
        third.call(/* leading */ only);
    }
}
